import json
import logging

import yaml
from pydantic import BaseModel

from app.config import get_settings
from app.enums import ApplicationStatus, ErrorCode
from app.logging import JsonFormatter, correlation_id_var, redact
from app.models import Base


def _contract():
    return yaml.safe_load(get_settings().openapi_path.read_text(encoding="utf-8"))


# ---------- health ----------
def test_live(client):
    r = client.get("/health/live")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_ready_503_when_db_down(client, monkeypatch):
    class Boom:
        def connect(self):
            raise RuntimeError("db down")

    monkeypatch.setattr("app.api.health.get_engine", lambda: Boom())
    r = client.get("/health/ready")
    assert r.status_code == 503
    assert r.json()["status"] == "not_ready"
    assert r.json()["checks"]["database"] == "unavailable"


# ---------- correlation id ----------
def test_correlation_id_generated(client):
    r = client.get("/health/live")
    assert len(r.headers["X-Correlation-ID"]) >= 32


def test_correlation_id_echoed(client):
    r = client.get("/health/live", headers={"X-Correlation-ID": "req-123"})
    assert r.headers["X-Correlation-ID"] == "req-123"


def test_correlation_id_invalid_replaced(client):
    r = client.get("/health/live", headers={"X-Correlation-ID": "bad id with spaces!"})
    assert r.headers["X-Correlation-ID"] != "bad id with spaces!"


def test_correlation_id_middleware_handles_missing_headers_key():
    import pytest
    from app.middleware import CorrelationIdMiddleware

    async def raw_asgi_app(scope, receive, send):
        # Simulates an ASGI app returning http.response.start without 'headers' key
        await send({"type": "http.response.start", "status": 204})
        await send({"type": "http.response.body", "body": b""})

    middleware = CorrelationIdMiddleware(raw_asgi_app)
    sent_messages = []

    async def mock_send(msg):
        sent_messages.append(msg)

    async def run_asgi():
        scope = {"type": "http", "method": "GET", "path": "/test", "headers": []}
        await middleware(scope, None, mock_send)

    import anyio
    anyio.run(run_asgi)

    start_msg = sent_messages[0]
    assert start_msg["type"] == "http.response.start"
    header_dict = dict(start_msg["headers"])
    assert b"x-correlation-id" in header_dict


def test_settings_jwt_secret_security(monkeypatch):
    import pytest
    from pydantic import ValidationError
    from app.config import Settings

    # Без JWT_SECRET в env Settings падает с ValidationError при запуске
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(ValidationError):
        Settings()

    # Секрет короче 16 символов падает с ValidationError
    with pytest.raises(ValidationError):
        Settings(jwt_secret="short")

    # Prod с placeholder "change-me-in-env" или коротким (<32) секретом падает с ошибкой
    with pytest.raises(ValueError, match="JWT_SECRET must be securely configured"):
        Settings(app_env="prod", jwt_secret="change-me-in-env")

    with pytest.raises(ValueError, match="JWT_SECRET must be securely configured"):
        Settings(app_env="prod", jwt_secret="short-prod-secret-16")


# ---------- формат ошибок ----------
def test_404_format(client):
    r = client.get("/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"
    assert "X-Correlation-ID" in r.headers


def test_validation_error_format(app, client):
    class Body(BaseModel):
        amount_rub: int

    @app.post("/_t/validate")
    def _validate(body: Body):
        return {}

    r = client.post("/_t/validate", json={"amount_rub": "abc"})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "VALIDATION_ERROR"
    assert err["details"][0]["field"] == "amount_rub"


def test_unhandled_error_is_hidden(app, client):
    @app.get("/_t/boom")
    def _boom():
        raise RuntimeError("secret internals")

    r = client.get("/_t/boom", headers={"X-Correlation-ID": "cid-500"})
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "secret" not in r.text
    assert r.headers["X-Correlation-ID"] == "cid-500"


# ---------- логи ----------
def test_redact_masks_sensitive_keys():
    out = redact({"password": "x", "nested": {"Authorization": "Bearer y", "ok": 1}, "inn": "0000001011"})
    assert out["password"] == "***" and out["nested"]["Authorization"] == "***"
    assert out["inn"] == "***" and out["nested"]["ok"] == 1


def test_json_log_has_correlation_and_no_pii():
    correlation_id_var.set("cid-1")
    rec = logging.LogRecord("t", logging.INFO, __file__, 1, "hello", (), None)
    rec.token = "SECRET-TOKEN"
    rec.status = 200
    data = json.loads(JsonFormatter().format(rec))
    assert data["correlation_id"] == "cid-1" and data["status"] == 200
    assert data["token"] == "***" and "SECRET-TOKEN" not in json.dumps(data)


# ---------- контракт ----------
def test_openapi_served_from_contract(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    assert r.json()["info"]["version"] == _contract()["info"]["version"]
    assert "/applications" in r.json()["paths"]


def test_docs_page(client):
    assert client.get("/docs").status_code == 200


def test_status_enum_matches_contract():
    schema = _contract()["components"]["schemas"]["ApplicationStatus"]["enum"]
    assert set(schema) == {s.value for s in ApplicationStatus}


def test_error_codes_match_contract():
    schemas = _contract()["components"]["schemas"]
    codes = schemas["ErrorResponse"]["properties"]["error"]["properties"]["code"]["enum"]
    assert set(codes) == {c.value for c in ErrorCode}


def test_tables_match_data_model():
    assert set(Base.metadata.tables) == {
        "users", "companies", "products", "applications", "application_status_history", "documents",
        "enrichment_results", "scoring_results", "decisions", "offers", "info_requests", "jobs",
    }
