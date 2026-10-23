"""Тесты для каталога продуктов и ручки рекомендаций."""
from app.models.tables import User
from tests.conftest import auth_headers


def test_list_products_empty(api_client):
    # Публичный доступ без токена
    resp = api_client.get("/api/v1/products")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_products_seeded(api_client, seed_products):
    resp = api_client.get("/api/v1/products")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    codes = [p["code"] for p in data]
    assert "WORKING_CAPITAL" in codes
    assert "EQUIPMENT" in codes
    assert "EXPRESS" in codes

    express = next(p for p in data if p["code"] == "EXPRESS")
    assert express["min_amount_rub"] == 100_000
    assert express["max_amount_rub"] == 1_500_000
    assert express["min_business_age_months"] == 12
    assert express["required_documents"] == []


def test_recommend_unauthorized(api_client):
    resp = api_client.post("/api/v1/products/recommend", json={"purpose": "EQUIPMENT"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHORIZED"


def test_recommend_equipment(api_client, client_user: User):
    resp = api_client.post(
        "/api/v1/products/recommend",
        json={"purpose": "EQUIPMENT", "amount_rub": 5_000_000},
        headers=auth_headers(client_user),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["product_code"] == "EQUIPMENT"
    assert data["source"] == "RULES"
    assert "оборудование" in data["explanation"].lower()


def test_recommend_urgent_cash_in_range(api_client, client_user: User):
    # Сумма от 100_000 до 1_500_000 при цели URGENT_CASH дает EXPRESS
    resp = api_client.post(
        "/api/v1/products/recommend",
        json={"purpose": "URGENT_CASH", "amount_rub": 800_000},
        headers=auth_headers(client_user),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["product_code"] == "EXPRESS"
    assert data["source"] == "RULES"


def test_recommend_urgent_cash_out_of_range(api_client, client_user: User):
    # Превышение 1.5 млн перенаправляет в WORKING_CAPITAL
    resp = api_client.post(
        "/api/v1/products/recommend",
        json={"purpose": "URGENT_CASH", "amount_rub": 2_000_000},
        headers=auth_headers(client_user),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["product_code"] == "WORKING_CAPITAL"


def test_recommend_working_capital_default(api_client, client_user: User):
    resp = api_client.post(
        "/api/v1/products/recommend",
        json={"purpose": "WORKING_CAPITAL", "amount_rub": 2_000_000},
        headers=auth_headers(client_user),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["product_code"] == "WORKING_CAPITAL"
    assert data["source"] == "RULES"


def test_recommend_invalid_purpose(api_client, client_user: User):
    resp = api_client.post(
        "/api/v1/products/recommend",
        json={"purpose": "INVALID_PURPOSE"},
        headers=auth_headers(client_user),
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
