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


# ---------- согласованность ошибок по ручкам ----------
import re  # noqa: E402

_HTTP_TO_CODES = {
    "401": {"UNAUTHORIZED"},
    "403": {"FORBIDDEN"},
    "404": {"NOT_FOUND"},
    "409": {"INVALID_TRANSITION", "CONFLICT", "VERSION_CONFLICT", "IDEMPOTENCY_CONFLICT"},
    "413": {"PAYLOAD_TOO_LARGE"},
    "422": {"VALIDATION_ERROR"},
    "429": {"RATE_LIMITED"},
}


def _operations():
    for path, ops in _contract()["paths"].items():
        for method, op in ops.items():
            if method in ("get", "post", "put", "patch", "delete"):
                yield method, path, op


def test_error_descriptions_use_known_codes_for_their_status():
    for method, path, op in _operations():
        for status, resp in op["responses"].items():
            if status not in _HTTP_TO_CODES:
                continue
            codes = set(re.findall(r"([A-Z][A-Z_]+) —", resp["description"]))
            assert codes, f"{method} {path} {status}: нет кода в описании"
            assert codes <= _HTTP_TO_CODES[status], f"{method} {path} {status}: {codes}"


def test_secured_operations_declare_401():
    for method, path, op in _operations():
        if op.get("security") != [] and not path.startswith("/health"):
            assert "401" in op["responses"], f"{method} {path}"


def test_id_paths_declare_404():
    for method, path, op in _operations():
        if "{id}" in path:
            assert "404" in op["responses"], f"{method} {path}"


def test_operator_routes_declare_403():
    for method, path, op in _operations():
        if path.startswith("/operator"):
            assert "403" in op["responses"], f"{method} {path}"


def test_operator_queue_documents_empty_result():
    ok = _contract()["paths"]["/operator/queue"]["get"]["responses"]["200"]
    examples = ok["content"]["application/json"]["examples"]
    assert examples["empty"]["value"] == []
    assert "X-Total-Count" in ok["headers"]
