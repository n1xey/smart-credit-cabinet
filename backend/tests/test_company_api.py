"""Тесты эндпоинтов профиля компании и lookup по ЕГРЮЛ."""
from app.api.schemas.company import CompanyInput
from app.enums import LegalForm, Role
from app.models.tables import User
from app.services.egrul_port import StubEgrulClient, get_egrul_client
from tests.conftest import _make_user, auth_headers


def test_get_company_unauthorized(api_client):
    resp = api_client.get("/api/v1/company")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHORIZED"


def test_get_company_forbidden_for_operator(api_client, operator_user: User):
    resp = api_client.get("/api/v1/company", headers=auth_headers(operator_user))
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_get_company_not_found(api_client, client_user: User):
    resp = api_client.get("/api/v1/company", headers=auth_headers(client_user))
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_create_and_update_company(api_client, client_user: User):
    # 1. Создание компании (ООО, 10 цифр)
    payload = {
        "inn": "0000001011",
        "name": "ООО «Ромашка»",
        "legal_form": "OOO",
        "registration_date": "2020-05-15",
        "okved": "62.01",
        "address": "г. Москва, ул. Ленина, д. 1",
    }
    resp = api_client.put("/api/v1/company", json=payload, headers=auth_headers(client_user))
    assert resp.status_code == 200
    data = resp.json()
    assert data["inn"] == "0000001011"
    assert data["name"] == "ООО «Ромашка»"
    assert "id" in data

    # 2. Чтение созданной компании через GET
    get_resp = api_client.get("/api/v1/company", headers=auth_headers(client_user))
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == data["id"]

    # 3. Обновление полей компании через повторный PUT
    payload["address"] = "г. Москва, ул. Новая, д. 2"
    update_resp = api_client.put("/api/v1/company", json=payload, headers=auth_headers(client_user))
    assert update_resp.status_code == 200
    assert update_resp.json()["id"] == data["id"]
    assert update_resp.json()["address"] == "г. Москва, ул. Новая, д. 2"


def test_put_company_length_validation(api_client, client_user: User):
    # ООО с 12 цифрами -> 422
    resp_ooo = api_client.put(
        "/api/v1/company",
        json={"inn": "000000070777", "name": "Тест", "legal_form": "OOO"},
        headers=auth_headers(client_user),
    )
    assert resp_ooo.status_code == 422
    assert resp_ooo.json()["error"]["code"] == "VALIDATION_ERROR"

    # ИП с 10 цифрами -> 422
    resp_ip = api_client.put(
        "/api/v1/company",
        json={"inn": "0000001011", "name": "ИП Иванов", "legal_form": "IP"},
        headers=auth_headers(client_user),
    )
    assert resp_ip.status_code == 422
    assert resp_ip.json()["error"]["code"] == "VALIDATION_ERROR"


def test_put_company_inn_conflict(api_client, db_session, client_user: User):
    # Создаем компанию для client_user
    payload = {
        "inn": "0000001011",
        "name": "ООО «Первый»",
        "legal_form": "OOO",
    }
    resp1 = api_client.put("/api/v1/company", json=payload, headers=auth_headers(client_user))
    assert resp1.status_code == 200

    # Создаем второго пользователя
    other_client = _make_user(db_session, "other_client@example.com", Role.CLIENT.value)

    # Второй пользователь пытается занять тот же ИНН -> 409 CONFLICT
    resp2 = api_client.put(
        "/api/v1/company",
        json={"inn": "0000001011", "name": "ООО «Второй»", "legal_form": "OOO"},
        headers=auth_headers(other_client),
    )
    assert resp2.status_code == 409
    assert resp2.json()["error"]["code"] == "CONFLICT"


def test_lookup_company_not_found(api_client, client_user: User):
    # При отсутствии ИНН в реестре возвращается 404 NOT_FOUND (без подмены)
    resp = api_client.get(
        "/api/v1/company/lookup?inn=0000009999",
        headers=auth_headers(client_user),
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_lookup_company_success(app_with_db, api_client, client_user: User):
    # Регистрируем компанию в тестовой заглушке
    stub_client = StubEgrulClient()
    test_company = CompanyInput(
        inn="0000001011",
        name="ООО «Ромашка»",
        legal_form=LegalForm.OOO,
        registration_date="2020-05-15",
        okved="62.01",
        address="г. Москва",
    )
    stub_client.register("0000001011", test_company)
    app_with_db.dependency_overrides[get_egrul_client] = lambda: stub_client

    resp = api_client.get(
        "/api/v1/company/lookup?inn=0000001011",
        headers=auth_headers(client_user),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["inn"] == "0000001011"
    assert data["name"] == "ООО «Ромашка»"
    assert data["legal_form"] == "OOO"
