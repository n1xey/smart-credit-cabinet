"""Низкоуровневые примитивы безопасности: хэш пароля и JWT.

Зависимости:
- bcrypt>=5.0 — хэширование паролей напрямую (без passlib; passlib не поддерживает bcrypt>=4)
- python-jose[cryptography]>=3.3 — HS256 JWT
"""
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
from jose import JWTError, jwt

from app.config import get_settings


def hash_password(plain: str) -> str:
    """Возвращает bcrypt-хэш пароля (salt генерируется автоматически)."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Проверяет пароль против bcrypt-хэша."""
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(user_id: uuid.UUID, role: str, email: str) -> str:
    """Создаёт HS256 JWT с claims: sub, role, email, exp, iat."""
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": role,
        "email": email,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_ttl_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict:
    """Декодирует и валидирует JWT. При ошибке бросает ValueError."""
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except JWTError as exc:
        raise ValueError(f"Invalid token: {exc}") from exc
