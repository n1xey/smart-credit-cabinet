"""Pydantic-схемы для Auth-эндпоинтов.

Строго по docs/api/openapi.yaml (v0.2):
  RegisterRequest, LoginRequest, TokenResponse, User (ответ /me).
"""
import uuid
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    """POST /auth/register — тело запроса."""

    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str

    @field_validator("email", mode="after")
    @classmethod
    def normalize_email(cls, v: EmailStr) -> str:
        return str(v).strip().lower()


class LoginRequest(BaseModel):
    """POST /auth/login — тело запроса. У пароля нет ограничения длины."""

    email: EmailStr
    password: str

    @field_validator("email", mode="after")
    @classmethod
    def normalize_email(cls, v: EmailStr) -> str:
        return str(v).strip().lower()


class UserResponse(BaseModel):
    """Вложенный объект User в TokenResponse и ответ GET /auth/me."""

    id: uuid.UUID
    email: EmailStr
    full_name: str | None = None
    role: Literal["CLIENT", "OPERATOR", "ADMIN"]


class TokenResponse(BaseModel):
    """Ответ на register и login."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: UserResponse
