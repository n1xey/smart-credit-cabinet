"""Схемы для офферов, запросов уточнений и подписания."""
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
