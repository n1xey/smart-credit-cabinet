"""Схемы для офферов, запросов уточнений и подписания."""
import datetime as dt
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.enums import DocType


class InfoRequestItem(BaseModel):
    code: str
    message: str
    doc_type: DocType | None = None


class InfoRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    items: list[dict[str, Any]]
    requested_by: str
    round: int
    created_at: datetime


class CorrectedFieldsSchema(BaseModel):
    """Строгая схема валидации исправляемых полей заявки и компании."""
    model_config = ConfigDict(extra="forbid")

    # Поля кредитной заявки
    amount_rub: int | None = Field(default=None, gt=0, description="Сумма кредита в рублях")
    term_months: int | None = Field(default=None, gt=0, description="Срок кредита в месяцах")
    purpose: str | None = Field(default=None, min_length=1, max_length=500, description="Цель кредита")
    revenue_12m_rub: int | None = Field(default=None, gt=0, description="Выручка за 12 месяцев")
    net_profit_12m_rub: int | None = Field(default=None, description="Чистая прибыль за 12 месяцев")
    existing_monthly_payments_rub: int | None = Field(default=None, ge=0, description="Ежемесячные платежи по другим кредитам")

    # Поля профиля компании
    name: str | None = Field(default=None, min_length=1, max_length=255, description="Наименование компании")
    okved: str | None = Field(default=None, min_length=1, max_length=20, description="Код ОКВЭД")
    address: str | None = Field(default=None, min_length=1, max_length=500, description="Юридический адрес")
    registration_date: dt.date | None = Field(default=None, description="Дата регистрации компании")


class InfoResponseInput(BaseModel):
    comment: str | None = Field(default=None, max_length=1000)
    corrected_fields: dict[str, Any] | None = None


class OfferResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID | None = None
    kind: str
    amount_rub: int
    term_months: int
    rate_percent: float
    monthly_payment_rub: int
    valid_until: datetime
    state: str = "ACTIVE"
    explanation: str | None = None
