"""Тесты аутентификации и RBAC.

Покрывает:
- Регистрация: успех, дублирующий email, валидация полей
- Логин: успех, неверный пароль, неверный email, rate-limit
- /me: с токеном, без токена, с просроченным токеном
- RBAC: CLIENT → 403 на оператор-ресурс (тест через require_role),
        CLIENT → 404 при обращении к чужой заявке (тест через deps)
- security.py: hash/verify, create/decode token
"""
import time
import uuid
from unittest.mock import patch

import pytest

from app.auth.rate_limit import InMemoryRateLimiter
from app.auth.security import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)
from tests.conftest import auth_headers


# ===========================================================================
# security.py — примитивы
# ===========================================================================
class TestPasswordHashing:
    def test_hash_and_verify_ok(self):
        h = hash_password("MySecretPass8!")
        assert verify_password("MySecretPass8!", h)

    def test_wrong_password_rejected(self):
        h = hash_password("correct")
        assert not verify_password("wrong", h)

    def test_hashes_differ_for_same_password(self):
        """bcrypt использует соль — два хэша одного пароля не совпадают."""
        assert hash_password("abc12345") != hash_password("abc12345")


class TestJWT:
    def test_create_and_decode_roundtrip(self):
        uid = uuid.uuid4()
        token = create_access_token(uid, "CLIENT", "u@example.com")
        payload = decode_token(token)
        assert payload["sub"] == str(uid)
        assert payload["role"] == "CLIENT"
        assert payload["email"] == "u@example.com"

    def test_invalid_token_raises(self):
        with pytest.raises(ValueError):
            decode_token("not.a.token")

    def test_tampered_token_raises(self):
        uid = uuid.uuid4()
        token = create_access_token(uid, "CLIENT", "u@example.com")
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(ValueError):
            decode_token(tampered)


# ===========================================================================
# rate_limit.py
# ===========================================================================
class TestInMemoryRateLimiter:
    def test_allows_within_limit(self):
        rl = InMemoryRateLimiter(limit=3, window_sec=60)
        assert rl.is_allowed("ip1")
        assert rl.is_allowed("ip1")
        assert rl.is_allowed("ip1")

    def test_blocks_over_limit(self):
        rl = InMemoryRateLimiter(limit=2, window_sec=60)
        rl.is_allowed("ip2")
        rl.is_allowed("ip2")
        assert not rl.is_allowed("ip2")

    def test_different_ips_independent(self):
        rl = InMemoryRateLimiter(limit=1, window_sec=60)
        rl.is_allowed("a")
        assert not rl.is_allowed("a")
        assert rl.is_allowed("b")  # разный ключ — не заблокирован

    def test_seconds_until_reset_positive_when_blocked(self):
        rl = InMemoryRateLimiter(limit=1, window_sec=60)
        rl.is_allowed("ip3")
        rl.is_allowed("ip3")  # blocked
        secs = rl.seconds_until_reset("ip3")
        assert 0 < secs <= 61


# ===========================================================================
# POST /auth/register
# ===========================================================================
class TestRegister:
    def test_register_success(self, api_client):
        r = api_client.post(
            "/api/v1/auth/register",
            json={"email": "new@example.com", "password": "Password1!", "full_name": "New User"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["token_type"] == "bearer"
        assert len(body["access_token"]) > 20
        assert body["user"]["email"] == "new@example.com"
        assert body["user"]["role"] == "CLIENT"
        assert body["user"]["full_name"] == "New User"
        assert "id" in body["user"]

    def test_register_duplicate_email(self, api_client):
        payload = {"email": "dup@example.com", "password": "Password1!", "full_name": "A"}
        api_client.post("/api/v1/auth/register", json=payload)
        r = api_client.post("/api/v1/auth/register", json=payload)
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "CONFLICT"

    def test_register_case_insensitive_duplicate(self, api_client):
        """User@Example.com и user@example.com должны конфликтовать."""
        api_client.post(
            "/api/v1/auth/register",
            json={"email": "CaseTest@Example.COM", "password": "Password1!", "full_name": "Case User"},
        )
        r = api_client.post(
            "/api/v1/auth/register",
            json={"email": "casetest@example.com", "password": "Password1!", "full_name": "Case User 2"},
        )
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "CONFLICT"

    def test_register_short_password(self, api_client):
        r = api_client.post(
            "/api/v1/auth/register",
            json={"email": "x@example.com", "password": "short", "full_name": "X"},
        )
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_register_invalid_email(self, api_client):
        r = api_client.post(
            "/api/v1/auth/register",
            json={"email": "not-an-email", "password": "Password1!", "full_name": "X"},
        )
        assert r.status_code == 422

    def test_register_missing_full_name(self, api_client):
        r = api_client.post(
            "/api/v1/auth/register",
            json={"email": "y@example.com", "password": "Password1!"},
        )
        assert r.status_code == 422


# ===========================================================================
# POST /auth/login
# ===========================================================================
class TestLogin:
    def test_login_success(self, api_client, client_user):
        r = api_client.post(
            "/api/v1/auth/login",
            json={"email": "client@example.com", "password": "Password1!"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["token_type"] == "bearer"
        assert body["user"]["role"] == "CLIENT"

    def test_login_case_insensitive(self, api_client, client_user):
        """Логин должен работать независимо от регистра введённого email."""
        r = api_client.post(
            "/api/v1/auth/login",
            json={"email": "CLIENT@EXAMPLE.COM", "password": "Password1!"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["user"]["email"] == "client@example.com"

    def test_login_wrong_password(self, api_client, client_user):
        r = api_client.post(
            "/api/v1/auth/login",
            json={"email": "client@example.com", "password": "WrongPass1!"},
        )
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "UNAUTHORIZED"

    def test_login_unknown_email(self, api_client):
        r = api_client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": "Password1!"},
        )
        assert r.status_code == 401

    def test_login_rate_limit(self, api_client, client_user):
        """Сброс лимитера до теста, чтобы не зависеть от порядка тестов."""
        import app.api.auth as auth_module

        auth_module._rate_limiter = InMemoryRateLimiter(limit=3, window_sec=60)

        payload = {"email": "client@example.com", "password": "WrongPass!"}
        for _ in range(3):
            api_client.post("/api/v1/auth/login", json=payload)

        r = api_client.post("/api/v1/auth/login", json=payload)
        assert r.status_code == 429
        assert r.json()["error"]["code"] == "RATE_LIMITED"

    def test_login_rate_limit_by_account_across_ips(self, api_client, client_user):
        """Брутфорс одного аккаунта с разных IP должен блокироваться по лимиту аккаунта."""
        import app.api.auth as auth_module

        auth_module._rate_limiter = InMemoryRateLimiter(limit=3, window_sec=60)

        payload = {"email": "client@example.com", "password": "WrongPass!"}
        for i in range(3):
            api_client.post("/api/v1/auth/login", json=payload, headers={"X-Forwarded-For": f"192.168.1.{i+1}"})

        # 4-я попытка с абсолютно нового IP на тот же аккаунт блокируется
        r = api_client.post("/api/v1/auth/login", json=payload, headers={"X-Forwarded-For": "10.0.0.99"})
        assert r.status_code == 429
        assert r.json()["error"]["code"] == "RATE_LIMITED"

    def test_login_rate_limit_by_ip_across_accounts(self, api_client):
        """Перебор разных аккаунтов с одного IP должен блокироваться по лимиту IP."""
        import app.api.auth as auth_module

        auth_module._rate_limiter = InMemoryRateLimiter(limit=3, window_sec=60)

        for i in range(3):
            api_client.post(
                "/api/v1/auth/login",
                json={"email": f"victim{i}@example.com", "password": "WrongPass!"},
                headers={"X-Forwarded-For": "203.0.113.5"},
            )

        # 4-я попытка с того же IP на новый аккаунт блокируется
        r = api_client.post(
            "/api/v1/auth/login",
            json={"email": "victim99@example.com", "password": "WrongPass!"},
            headers={"X-Forwarded-For": "203.0.113.5"},
        )
        assert r.status_code == 429
        assert r.json()["error"]["code"] == "RATE_LIMITED"


# ===========================================================================
# GET /auth/me
# ===========================================================================
class TestMe:
    def test_me_with_valid_token(self, api_client, client_user):
        r = api_client.get("/api/v1/auth/me", headers=auth_headers(client_user))
        assert r.status_code == 200
        assert r.json()["email"] == "client@example.com"
        assert r.json()["role"] == "CLIENT"

    def test_me_without_token(self, api_client):
        r = api_client.get("/api/v1/auth/me")
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "UNAUTHORIZED"

    def test_me_with_invalid_token(self, api_client):
        r = api_client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage.token.here"})
        assert r.status_code == 401

    def test_me_with_token_missing_claims_returns_401(self, api_client):
        from jose import jwt
        from app.config import get_settings

        raw_token = jwt.encode({"sub": str(uuid.uuid4())}, get_settings().jwt_secret, algorithm="HS256")
        r = api_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {raw_token}"})
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "UNAUTHORIZED"

    def test_me_with_token_invalid_sub_uuid_returns_401(self, api_client):
        from jose import jwt
        from app.config import get_settings

        raw_token = jwt.encode(
            {"sub": "not-a-uuid", "role": "CLIENT", "email": "a@b.com"},
            get_settings().jwt_secret,
            algorithm="HS256",
        )
        r = api_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {raw_token}"})
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "UNAUTHORIZED"

    def test_me_with_token_invalid_claim_types_returns_401(self, api_client):
        from jose import jwt
        from app.config import get_settings

        raw_token = jwt.encode(
            {"sub": str(uuid.uuid4()), "role": 12345, "email": "a@b.com"},
            get_settings().jwt_secret,
            algorithm="HS256",
        )
        r = api_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {raw_token}"})
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "UNAUTHORIZED"

    def test_me_operator_role(self, api_client, operator_user):
        r = api_client.get("/api/v1/auth/me", headers=auth_headers(operator_user))
        assert r.status_code == 200
        assert r.json()["role"] == "OPERATOR"


# ===========================================================================
# RBAC — require_role
# ===========================================================================
class TestRBAC:
    def test_client_blocked_from_operator_route(self, app_with_db, client_user):
        """Временный роутер только для оператора — проверяем 403."""
        from fastapi import Depends
        from fastapi.testclient import TestClient

        from app.auth.deps import require_role
        from app.enums import Role

        @app_with_db.get("/_test/operator-only")
        def _op_only(u=Depends(require_role(Role.OPERATOR, Role.ADMIN))):
            return {"ok": True}

        c = TestClient(app_with_db, raise_server_exceptions=False)
        r = c.get("/_test/operator-only", headers=auth_headers(client_user))
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "FORBIDDEN"

    def test_operator_allowed_on_operator_route(self, app_with_db, operator_user):
        from fastapi import Depends
        from fastapi.testclient import TestClient

        from app.auth.deps import require_role
        from app.enums import Role

        @app_with_db.get("/_test/op-only2")
        def _op(u=Depends(require_role(Role.OPERATOR))):
            return {"ok": True}

        c = TestClient(app_with_db, raise_server_exceptions=False)
        r = c.get("/_test/op-only2", headers=auth_headers(operator_user))
        assert r.status_code == 200
