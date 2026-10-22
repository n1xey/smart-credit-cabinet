"""FastAPI-зависимости для аутентификации и RBAC."""
import logging
import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.security import decode_token
from app.enums import ErrorCode, Role

log = logging.getLogger("app.auth")

_bearer = HTTPBearer(auto_error=False)


@dataclass
class TokenData:
    user_id: uuid.UUID
    role: str
    email: str


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> TokenData:
    """Проверяет Bearer-токен и возвращает TokenData. 401 если токен отсутствует или невалиден."""
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
        )
    try:
        payload = decode_token(credentials.credentials)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return TokenData(
        user_id=uuid.UUID(payload["sub"]),
        role=payload["role"],
        email=payload["email"],
    )


def require_role(*roles: Role):
    """Фабрика зависимостей: пропускает только указанные роли, иначе 403 FORBIDDEN."""

    def _dep(current_user: TokenData = Depends(get_current_user)) -> TokenData:
        if current_user.role not in {r.value for r in roles}:
            raise HTTPException(
                status_code=403,
                detail="Insufficient permissions",
            )
        return current_user

    return _dep
