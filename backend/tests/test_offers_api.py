"""Тесты API офферов, ответов на запросы уточнений и подписания."""
import datetime
import uuid

import pytest
from sqlalchemy import select

from app.enums import ApplicationStatus, DocType, LegalForm, OfferKind, OfferState, Role
from app.models.tables import Application, ApplicationStatusHistory, Company, InfoRequest, Offer
from tests.conftest import _make_user, auth_headers


@pytest.fixture
def client_with_company(db_session, client_user):
    comp = Company(
        id=uuid.uuid4(),
        owner_id=client_user.id,
        inn="7707083893",
        name="ООО Тест Оффер",
        legal_form=LegalForm.OOO.value,
        registration_date=datetime.date(2020, 1, 1),
    )
    db_session.add(comp)
    db_session.commit()
    db_session.refresh(comp)
    return client_user, comp


@pytest.fixture
def other_client_with_company(db_session):
    other_user = _make_user(db_session, "other_client_offers@example.com", Role.CLIENT.value, "Чужой Клиент Оффер")
    comp = Company(
        id=uuid.uuid4(),
        owner_id=other_user.id,
        inn="7707083894",
        name="ООО Другая Компания",
        legal_form=LegalForm.OOO.value,
    )
    db_session.add(comp)
    db_session.commit()
    db_session.refresh(comp)
    return other_user, comp


@pytest.fixture
def needs_info_application(db_session, client_with_company, seed_products):
    user, company = client_with_company
    app = Application(
        id=uuid.uuid4(),
        company_id=company.id,
        created_by=user.id,
        product_code="WORKING_CAPITAL",
        amount_rub=2_000_000,
        term_months=12,
        purpose="Пополнение оборотных средств",
        status=ApplicationStatus.NEEDS_INFO.value,
        version=1,
    )
    db_session.add(app)
    db_session.flush()

    info_req = InfoRequest(
        id=uuid.uuid4(),
        application_id=app.id,
        round=1,
        items=[
            {
                "code": "DOCUMENT_MISSING",
                "message": "Приложите бухгалтерскую отчетность",
                "doc_type": DocType.FINANCIAL_STATEMENT.value,
            }
        ],
        requested_by="SYSTEM",
    )
    db_session.add(info_req)
    db_session.commit()
    db_session.refresh(app)
    return app, info_req


@pytest.fixture
def offer_application(db_session, client_with_company, seed_products):
    user, company = client_with_company
    app = Application(
        id=uuid.uuid4(),
        company_id=company.id,
        created_by=user.id,
        product_code="WORKING_CAPITAL",
        amount_rub=2_000_000,
        term_months=12,
        purpose="Пополнение оборотных средств",
        status=ApplicationStatus.OFFER.value,
        version=1,
    )
    db_session.add(app)
    db_session.flush()

    offer = Offer(
        id=uuid.uuid4(),
        application_id=app.id,
        kind=OfferKind.ORIGINAL.value,
        amount_rub=2_000_000,
        term_months=12,
        rate_percent=18.0,
        monthly_payment_rub=183360,
        valid_until=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3),
        state=OfferState.ACTIVE.value,
    )
    db_session.add(offer)
    db_session.commit()
    db_session.refresh(app)
    return app, offer


def test_get_info_request_and_isolation(api_client, client_user, other_client_with_company, needs_info_application):
    app, info_req = needs_info_application
    other_user, _ = other_client_with_company

    # 1. Успешное получение запроса клиентом
    resp = api_client.get(
        f"/api/v1/applications/{app.id}/info-request",
        headers=auth_headers(client_user),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(info_req.id)
    assert data["round"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["code"] == "DOCUMENT_MISSING"

    # 2. Чужой клиент получает строго 404
    resp_other = api_client.get(
        f"/api/v1/applications/{app.id}/info-request",
        headers=auth_headers(other_user),
    )
    assert resp_other.status_code == 404
    assert resp_other.json()["error"]["code"] == "NOT_FOUND"


def test_answer_info_request_whitelist_validation(api_client, client_user, needs_info_application):
    app, _ = needs_info_application

    # 1. Поле inn запрещено для корректировки
    resp = api_client.post(
        f"/api/v1/applications/{app.id}/info-request",
        json={"corrected_fields": {"inn": "7707083893"}},
        headers=auth_headers(client_user),
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    # 2. Неизвестное поле
    resp = api_client.post(
        f"/api/v1/applications/{app.id}/info-request",
        json={"corrected_fields": {"random_field": "val"}},
        headers=auth_headers(client_user),
    )
    assert resp.status_code == 422

    # 3. Некорректный тип для amount_rub
    resp = api_client.post(
        f"/api/v1/applications/{app.id}/info-request",
        json={"corrected_fields": {"amount_rub": -100}},
        headers=auth_headers(client_user),
    )
    assert resp.status_code == 422

    # 4. Отрицательная выручка revenue_12m_rub
    resp = api_client.post(
        f"/api/v1/applications/{app.id}/info-request",
        json={"corrected_fields": {"revenue_12m_rub": -50_000}},
        headers=auth_headers(client_user),
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    # 5. Отрицательные текущие платежи existing_monthly_payments_rub
    resp = api_client.post(
        f"/api/v1/applications/{app.id}/info-request",
        json={"corrected_fields": {"existing_monthly_payments_rub": -1000}},
        headers=auth_headers(client_user),
    )
    assert resp.status_code == 422

    # 6. Сумма amount_rub больше максимума продукта (WORKING_CAPITAL max = 10_000_000)
    resp = api_client.post(
        f"/api/v1/applications/{app.id}/info-request",
        json={"corrected_fields": {"amount_rub": 99_000_000}},
        headers=auth_headers(client_user),
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    # 7. Срок term_months меньше минимума продукта (WORKING_CAPITAL min = 3)
    resp = api_client.post(
        f"/api/v1/applications/{app.id}/info-request",
        json={"corrected_fields": {"term_months": 1}},
        headers=auth_headers(client_user),
    )
    assert resp.status_code == 422

    # 8. Пустая цель purpose
    resp = api_client.post(
        f"/api/v1/applications/{app.id}/info-request",
        json={"corrected_fields": {"purpose": ""}},
        headers=auth_headers(client_user),
    )
    assert resp.status_code == 422


def test_answer_info_request_success(api_client, client_user, needs_info_application, db_session):
    app, info_req = needs_info_application

    payload = {
        "comment": "Обновили сумму и адрес компании",
        "corrected_fields": {
            "amount_rub": 1_800_000,
            "address": "г. Москва, ул. Тверская, д. 1",
            "name": "ООО Обновлённое Имя",
            "registration_date": "2021-03-10",
        },
    }

    resp = api_client.post(
        f"/api/v1/applications/{app.id}/info-request",
        json=payload,
        headers=auth_headers(client_user),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "DATA_CHECK"
    assert data["amount_rub"] == 1_800_000
    assert data["company_name"] == "ООО Обновлённое Имя"

    # Проверяем БД
    db_session.refresh(app)
    assert app.status == ApplicationStatus.DATA_CHECK.value
    assert app.amount_rub == 1_800_000

    db_company = db_session.scalar(select(Company).where(Company.id == app.company_id))
    assert db_company.name == "ООО Обновлённое Имя"
    assert db_company.address == "г. Москва, ул. Тверская, д. 1"
    assert str(db_company.registration_date) == "2021-03-10"

    db_session.refresh(info_req)
    assert info_req.answered_at is not None
    assert info_req.response["comment"] == "Обновили сумму и адрес компании"


def test_get_offer_and_isolation(api_client, client_user, other_client_with_company, offer_application):
    app, offer = offer_application
    other_user, _ = other_client_with_company

    # 1. Просмотр оффера клиентом
    resp = api_client.get(f"/api/v1/applications/{app.id}/offer", headers=auth_headers(client_user))
    assert resp.status_code == 200
    data = resp.json()
    assert data["amount_rub"] == offer.amount_rub
    assert data["rate_percent"] == offer.rate_percent
    assert data["kind"] == offer.kind
    assert data["state"] == "ACTIVE"

    # 2. Чужой клиент -> 404
    resp_other = api_client.get(f"/api/v1/applications/{app.id}/offer", headers=auth_headers(other_user))
    assert resp_other.status_code == 404

    # 3. В статусе DRAFT оффер недоступен (строго 404), даже если в БД есть активная запись Offer
    app.status = ApplicationStatus.DRAFT.value
    resp_draft = api_client.get(f"/api/v1/applications/{app.id}/offer", headers=auth_headers(client_user))
    assert resp_draft.status_code == 404
    assert resp_draft.json()["error"]["code"] == "NOT_FOUND"


def test_accept_offer_with_and_without_if_match(api_client, client_user, offer_application, db_session):
    app, offer = offer_application

    # 1. Неверный If-Match -> 409 VERSION_CONFLICT
    resp = api_client.post(
        f"/api/v1/applications/{app.id}/offer/accept",
        headers={**auth_headers(client_user), "If-Match": '"999"'},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "VERSION_CONFLICT"

    # 2. Успешный accept с верным If-Match
    resp = api_client.post(
        f"/api/v1/applications/{app.id}/offer/accept",
        headers={**auth_headers(client_user), "If-Match": f'"{app.version}"'},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ACCEPTED"

    # Проверяем синхронизацию статуса оффера в БД
    db_session.refresh(offer)
    assert offer.state == "ACCEPTED"

    # 3. Повторный accept в статусе ACCEPTED -> 409 INVALID_TRANSITION
    resp_repeat = api_client.post(
        f"/api/v1/applications/{app.id}/offer/accept",
        headers=auth_headers(client_user),
    )
    assert resp_repeat.status_code == 409
    assert resp_repeat.json()["error"]["code"] == "INVALID_TRANSITION"


def test_accept_expired_offer_fails(api_client, client_user, offer_application, db_session):
    app, offer = offer_application
    # Истёкший оффер
    offer.valid_until = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
    db_session.commit()

    resp = api_client.post(
        f"/api/v1/applications/{app.id}/offer/accept",
        headers=auth_headers(client_user),
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "INVALID_TRANSITION"


def test_decline_offer_success(api_client, client_user, offer_application, db_session):
    app, offer = offer_application

    resp = api_client.post(
        f"/api/v1/applications/{app.id}/offer/decline",
        headers=auth_headers(client_user),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "CANCELLED"

    db_session.refresh(app)
    assert app.status == ApplicationStatus.CANCELLED.value
    db_session.refresh(offer)
    assert offer.state == "DECLINED"


def test_sign_application_lifecycle(api_client, client_user, offer_application, db_session):
    app, _ = offer_application

    # 1. В статусе OFFER подписание запрещено -> 409
    resp = api_client.post(f"/api/v1/applications/{app.id}/sign", headers=auth_headers(client_user))
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "INVALID_TRANSITION"

    # Переводим в SIGNING (как после работы системного воркера)
    app.status = ApplicationStatus.SIGNING.value
    db_session.commit()

    # 2. Успешное подписание
    resp = api_client.post(f"/api/v1/applications/{app.id}/sign", headers=auth_headers(client_user))
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "DISBURSED"
    assert data["next_action"] == "NONE"

    db_session.refresh(app)
    assert app.status == ApplicationStatus.DISBURSED.value
