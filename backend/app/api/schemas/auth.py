"""Pydantic-схемы для Auth-эндпоинтов.

Строго по docs/api/openapi.yaml (v0.2):
  RegisterRequest, LoginRequest, TokenResponse, User (ответ /me).
"""
import uuid
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    """POST /auth/register — тело запроса."""

    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str


class LoginRequest(BaseModel):
    """POST /auth/login — тело запроса. У пароля нет ограничения длины."""

    email: EmailStr
    password: str


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
