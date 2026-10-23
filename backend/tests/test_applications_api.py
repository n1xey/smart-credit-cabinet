"""Интеграционные тесты для API заявок (Applications lifecycle)."""
import datetime
import uuid

import pytest

from app.api.schemas.company import CompanyInput
from app.enums import ApplicationStatus, LegalForm, Role
from app.models.tables import Application, Company, Product, User
from tests.conftest import _make_user, auth_headers


@pytest.fixture
def client_with_company(db_session, client_user: User) -> tuple[User, Company]:
    comp = Company(
        id=uuid.uuid4(),
        owner_id=client_user.user_id if hasattr(client_user, "user_id") else client_user.id,
        inn="0000001011",
        name="ООО «Ромашка»",
        legal_form=LegalForm.OOO.value,
        registration_date=datetime.date(2020, 1, 1),  # 6+ лет
        okved="62.01",
        address="г. Москва",
    )
    db_session.add(comp)
    db_session.commit()
    db_session.refresh(comp)
    return client_user, comp


def test_create_draft_requires_company(api_client, client_user: User, seed_products):
    # Без компании -> 422 VALIDATION_ERROR
    resp = api_client.post(
        "/api/v1/applications",
        json={"product_code": "WORKING_CAPITAL", "amount_rub": 1_000_000, "term_months": 12},
        headers=auth_headers(client_user),
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_create_draft_success(api_client, client_with_company, seed_products):
    client, company = client_with_company
    payload = {
        "product_code": "WORKING_CAPITAL",
        "amount_rub": 1_000_000,
        "term_months": 12,
        "purpose": "Закупка сырья",
    }
    resp = api_client.post("/api/v1/applications", json=payload, headers=auth_headers(client))
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "DRAFT"
    assert data["version"] == 1
    assert data["company_name"] == company.name
    assert data["next_action"] == "FILL_DRAFT"
    assert data["status_title"] == "Черновик"
    assert data["amount_rub"] == 1_000_000


def test_list_applications_isolation_and_filters(api_client, db_session, client_with_company, seed_products):
    client, company = client_with_company

    # Создаем черновик для клиента 1
    resp = api_client.post(
        "/api/v1/applications",
        json={"product_code": "WORKING_CAPITAL", "amount_rub": 1_000_000, "term_months": 12},
        headers=auth_headers(client),
    )
    assert resp.status_code == 201
    app_id = resp.json()["id"]

    # Создаем второго клиента с компанией
    other_client = _make_user(db_session, "other@client.com", Role.CLIENT.value)
    other_comp = Company(
        id=uuid.uuid4(),
        owner_id=other_client.id,
        inn="0000002022",
        name="ООО «Второй»",
        legal_form=LegalForm.OOO.value,
        registration_date=datetime.date(2021, 1, 1),
    )
    db_session.add(other_comp)
    db_session.commit()

    # Клиент 2 запрашивает список — заявка клиента 1 не видна
    other_resp = api_client.get("/api/v1/applications", headers=auth_headers(other_client))
    assert other_resp.status_code == 200
    assert other_resp.json() == []
    assert other_resp.headers["X-Total-Count"] == "0"

    # Клиент 1 запрашивает список — видит свою заявку
    my_resp = api_client.get("/api/v1/applications?status=DRAFT", headers=auth_headers(client))
    assert my_resp.status_code == 200
    assert len(my_resp.json()) == 1
    assert my_resp.json()[0]["id"] == app_id
    assert my_resp.headers["X-Total-Count"] == "1"

    # Невалидный статус -> 422
    bad_resp = api_client.get("/api/v1/applications?status=INVALID", headers=auth_headers(client))
    assert bad_resp.status_code == 422


def test_get_application_etag_and_foreign_404(api_client, db_session, client_with_company, seed_products):
    client, company = client_with_company
    resp = api_client.post(
        "/api/v1/applications",
        json={"product_code": "WORKING_CAPITAL", "amount_rub": 1_000_000, "term_months": 12},
        headers=auth_headers(client),
    )
    app_id = resp.json()["id"]

    # Проверка ETag
    get_resp = api_client.get(f"/api/v1/applications/{app_id}", headers=auth_headers(client))
    assert get_resp.status_code == 200
    assert get_resp.headers["ETag"] == '"1"'

    # 304 Not Modified при совпадении If-None-Match
    cached_resp = api_client.get(
        f"/api/v1/applications/{app_id}",
        headers={**auth_headers(client), "If-None-Match": '"1"'},
    )
    assert cached_resp.status_code == 304

    # Чужой клиент получает 404 (сокрытие данных)
    other_client = _make_user(db_session, "other2@client.com", Role.CLIENT.value)
    foreign_resp = api_client.get(f"/api/v1/applications/{app_id}", headers=auth_headers(other_client))
    assert foreign_resp.status_code == 404
    assert foreign_resp.json()["error"]["code"] == "NOT_FOUND"


def test_patch_draft_with_and_without_if_match(api_client, client_with_company, seed_products, db_session):
    client, company = client_with_company
    create_resp = api_client.post(
        "/api/v1/applications",
        json={"product_code": "WORKING_CAPITAL", "amount_rub": 1_000_000, "term_months": 12},
        headers=auth_headers(client),
    )
    app_id = create_resp.json()["id"]

    # 1. Несовпадение If-Match -> 409 VERSION_CONFLICT
    conflict_resp = api_client.patch(
        f"/api/v1/applications/{app_id}",
        json={"amount_rub": 2_000_000},
        headers={**auth_headers(client), "If-Match": '"999"'},
    )
    assert conflict_resp.status_code == 409
    assert conflict_resp.json()["error"]["code"] == "VERSION_CONFLICT"

    # 2. Успешный PATCH с правильным If-Match
    ok_resp = api_client.patch(
        f"/api/v1/applications/{app_id}",
        json={"amount_rub": 2_000_000},
        headers={**auth_headers(client), "If-Match": '"1"'},
    )
    assert ok_resp.status_code == 200
    assert ok_resp.json()["amount_rub"] == 2_000_000
    assert ok_resp.json()["version"] == 2
    assert ok_resp.headers["ETag"] == '"2"'

    # 3. Успешный PATCH БЕЗ If-Match (заголовок optional)
    no_header_resp = api_client.patch(
        f"/api/v1/applications/{app_id}",
        json={"term_months": 18},
        headers=auth_headers(client),
    )
    assert no_header_resp.status_code == 200
    assert no_header_resp.json()["term_months"] == 18
    assert no_header_resp.json()["version"] == 3

    # 4. PATCH с продуктом, отсутствующим в БД products -> 422 VALIDATION_ERROR
    from app.models.tables import Product
    seed_products[2]  # EXPRESS
    # Удаляем один из продуктов из БД
    db_session.query(Product).filter(Product.code == "EXPRESS").delete()
    db_session.commit()

    missing_prod_resp = api_client.patch(
        f"/api/v1/applications/{app_id}",
        json={"product_code": "EXPRESS"},
        headers=auth_headers(client),
    )
    assert missing_prod_resp.status_code == 422
    assert missing_prod_resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_submit_validation_errors(api_client, client_with_company, seed_products):
    client, company = client_with_company
    create_resp = api_client.post(
        "/api/v1/applications",
        json={"product_code": "WORKING_CAPITAL", "amount_rub": 1_000_000, "term_months": 12},
        headers=auth_headers(client),
    )
    app_id = create_resp.json()["id"]

    # Попытка подать неполную заявку (нет выручки и платежей)
    submit_resp = api_client.post(
        f"/api/v1/applications/{app_id}/submit",
        headers={**auth_headers(client), "Idempotency-Key": "test-key-12345"},
    )
    assert submit_resp.status_code == 422
    err = submit_resp.json()["error"]
    assert err["code"] == "VALIDATION_ERROR"
    fields = [d["field"] for d in err["details"]]
    assert "revenue_12m_rub" in fields
    assert "net_profit_12m_rub" in fields
    assert "existing_monthly_payments_rub" in fields


def test_submit_idempotency_matrix(api_client, db_session, client_with_company, seed_products):
    client, company = client_with_company

    # Заполняем полную заявку
    create_resp = api_client.post(
        "/api/v1/applications",
        json={
            "product_code": "WORKING_CAPITAL",
            "amount_rub": 1_000_000,
            "term_months": 12,
            "revenue_12m_rub": 10_000_000,
            "net_profit_12m_rub": 1_000_000,
            "existing_monthly_payments_rub": 20_000,
        },
        headers=auth_headers(client),
    )
    app_id_1 = create_resp.json()["id"]

    key_1 = "valid-idempotency-key-001"

    # 1. Первый submit -> 202 ACCEPTED
    resp1 = api_client.post(
        f"/api/v1/applications/{app_id_1}/submit",
        headers={**auth_headers(client), "Idempotency-Key": key_1},
    )
    assert resp1.status_code == 202
    assert resp1.json()["status"] == "SUBMITTED"
    assert resp1.json()["next_action"] == "NONE"

    # 2. Повтор с тем же ключом на той же заявке -> тот же 202
    resp2 = api_client.post(
        f"/api/v1/applications/{app_id_1}/submit",
        headers={**auth_headers(client), "Idempotency-Key": key_1},
    )
    assert resp2.status_code == 202
    assert resp2.json()["status"] == "SUBMITTED"

    # 3. Другой ключ на уже поданной заявке -> 409 INVALID_TRANSITION
    resp3 = api_client.post(
        f"/api/v1/applications/{app_id_1}/submit",
        headers={**auth_headers(client), "Idempotency-Key": "another-key-9999"},
    )
    assert resp3.status_code == 409
    assert resp3.json()["error"]["code"] == "INVALID_TRANSITION"

    # 4. Тот же ключ на другой заявке -> 409 IDEMPOTENCY_CONFLICT
    create_resp2 = api_client.post(
        "/api/v1/applications",
        json={
            "product_code": "WORKING_CAPITAL",
            "amount_rub": 2_000_000,
            "term_months": 12,
            "revenue_12m_rub": 10_000_000,
            "net_profit_12m_rub": 1_000_000,
            "existing_monthly_payments_rub": 20_000,
        },
        headers=auth_headers(client),
    )
    app_id_2 = create_resp2.json()["id"]

    resp4 = api_client.post(
        f"/api/v1/applications/{app_id_2}/submit",
        headers={**auth_headers(client), "Idempotency-Key": key_1},
    )
    assert resp4.status_code == 409
    assert resp4.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    # 5. Заголовок Idempotency-Key отсутствует -> 422
    resp5 = api_client.post(
        f"/api/v1/applications/{app_id_2}/submit",
        headers=auth_headers(client),
    )
    assert resp5.status_code == 422


def test_cancel_application_and_history(api_client, client_with_company, seed_products):
    client, company = client_with_company
    create_resp = api_client.post(
        "/api/v1/applications",
        json={"product_code": "WORKING_CAPITAL", "amount_rub": 1_000_000, "term_months": 12},
        headers=auth_headers(client),
    )
    app_id = create_resp.json()["id"]

    # Отмена из DRAFT -> CANCELLED
    cancel_resp = api_client.post(f"/api/v1/applications/{app_id}/cancel", headers=auth_headers(client))
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "CANCELLED"

    # Чтение истории статусов
    hist_resp = api_client.get(f"/api/v1/applications/{app_id}/history", headers=auth_headers(client))
    assert hist_resp.status_code == 200
    history = hist_resp.json()
    assert len(history) == 2
    assert history[0]["to_status"] == "DRAFT"
    assert history[0]["reason_code"] == "DRAFT_CREATED"
    assert history[1]["to_status"] == "CANCELLED"
    assert history[1]["reason_code"] == "CLIENT_CANCELLED"
