"""Эндпоинты аутентификации: register, login, me.

POST /auth/register — без токена, роль всегда CLIENT, 201 + TokenResponse.
POST /auth/login    — без токена, rate-limit по IP, 200 + TokenResponse.
GET  /auth/me       — требует Bearer-токен, возвращает User.
"""
import logging

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from app.auth.deps import TokenData, get_current_user
from app.auth.rate_limit import InMemoryRateLimiter
from app.auth.security import create_access_token, hash_password, verify_password
from app.config import get_settings
from app.db import get_db
from app.enums import ErrorCode, Role
from app.errors import ApiError
from app.models.tables import User

log = logging.getLogger("app.api.auth")
router = APIRouter(prefix="/auth", tags=["Auth"])

# Rate-limiter — синглтон на процесс (согласно CLAUDE.md: без Redis в MVP)
_rate_limiter: InMemoryRateLimiter | None = None


def _get_rate_limiter() -> InMemoryRateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = InMemoryRateLimiter(
            limit=get_settings().login_rate_limit_per_minute,
            window_sec=60,
        )
    return _rate_limiter


def _client_ip(request: Request) -> str:
    """Извлекает IP клиента (учитывает X-Forwarded-For при наличии)."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _user_to_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
    )


# ---------------------------------------------------------------------------
# POST /auth/register
# ---------------------------------------------------------------------------
@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=TokenResponse)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    """Регистрация нового клиента. Роль всегда CLIENT. Email нормализуется (strip().lower())."""
    norm_email = body.email.strip().lower()
    existing = db.scalar(select(User).where(func.lower(User.email) == norm_email))
    if existing is not None:
        raise ApiError(
            status_code=409,
            code=ErrorCode.CONFLICT,
            message="Email уже зарегистрирован",
        )

    user = User(
        email=norm_email,
        full_name=body.full_name,
        password_hash=hash_password(body.password),
        role=Role.CLIENT.value,
    )
    db.add(user)
    try:
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        raise ApiError(
            status_code=409,
            code=ErrorCode.CONFLICT,
            message="Email уже зарегистрирован",
        )

    log.info("user_registered", extra={"user_id": str(user.id)})
    token = create_access_token(user.id, user.role, user.email)
    return TokenResponse(access_token=token, user=_user_to_response(user))


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------
@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    """Вход. Rate-limit по IP и по аккаунту: LOGIN_RATE_LIMIT_PER_MINUTE попыток за 60 с."""
    ip = _client_ip(request)
    norm_email = body.email.strip().lower()
    limiter = _get_rate_limiter()

    ip_key = f"ip:{ip}"
    account_key = f"acc:{norm_email}"

    if not limiter.is_allowed(ip_key) or not limiter.is_allowed(account_key):
        retry_after = max(limiter.seconds_until_reset(ip_key), limiter.seconds_until_reset(account_key))
        raise ApiError(
            status_code=429,
            code=ErrorCode.RATE_LIMITED,
            message="Слишком много попыток входа. Попробуйте позже.",
            details=[{"retry_after_seconds": retry_after}],
        )

    user = db.scalar(select(User).where(func.lower(User.email) == norm_email))
    if user is None or not verify_password(body.password, user.password_hash):
        raise ApiError(
            status_code=401,
            code=ErrorCode.UNAUTHORIZED,
            message="Неверный email или пароль",
        )

    log.info("user_login", extra={"user_id": str(user.id)})
    token = create_access_token(user.id, user.role, user.email)
    return TokenResponse(access_token=token, user=_user_to_response(user))


# ---------------------------------------------------------------------------
# GET /auth/me
# ---------------------------------------------------------------------------
@router.get("/me", response_model=UserResponse)
def me(
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Профиль текущего аутентифицированного пользователя."""
    user = db.get(User, current_user.user_id)
    if user is None:
        raise ApiError(status_code=401, code=ErrorCode.UNAUTHORIZED, message="Пользователь не найден")
    return _user_to_response(user)
