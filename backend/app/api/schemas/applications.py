"""Pydantic-схемы для заявок на получение кредита."""
import datetime
import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.enums import ApplicationStatus, NextAction, ProductCode


class ApplicationInput(BaseModel):
    product_code: ProductCode
    amount_rub: int = Field(..., ge=1, description="Запрашиваемая сумма в целых рублях")
    term_months: int = Field(..., ge=1, description="Запрашиваемый срок в месяцах")
    purpose: str | None = Field(default=None, max_length=500, description="Цель кредитования")
    revenue_12m_rub: int | None = Field(default=None, description="Выручка за последние 12 месяцев")
    net_profit_12m_rub: int | None = Field(default=None, description="Чистая прибыль за последние 12 месяцев")
    existing_monthly_payments_rub: int | None = Field(default=None, ge=0, description="Текущие платежи по кредитам в месяц")


class ApplicationPatch(BaseModel):
    product_code: ProductCode | None = None
    amount_rub: int | None = Field(default=None, ge=1)
    term_months: int | None = Field(default=None, ge=1)
    purpose: str | None = Field(default=None, max_length=500)
    revenue_12m_rub: int | None = None
    net_profit_12m_rub: int | None = None
    existing_monthly_payments_rub: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def check_at_least_one_field(self) -> "ApplicationPatch":
        fields = [
            self.product_code,
            self.amount_rub,
            self.term_months,
            self.purpose,
            self.revenue_12m_rub,
            self.net_profit_12m_rub,
            self.existing_monthly_payments_rub,
        ]
        if all(f is None for f in fields):
            raise ValueError("Для обновления необходимо указать хотя бы одно поле")
        return self


class ApplicationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_name: str
    status: ApplicationStatus
    product_code: str
    amount_rub: int | None = None
    term_months: int | None = None
    submitted_at: datetime.datetime | None = None
    updated_at: datetime.datetime


class ApplicationResponse(ApplicationSummary):
    version: int
    purpose: str | None = None
    revenue_12m_rub: int | None = None
    net_profit_12m_rub: int | None = None
    existing_monthly_payments_rub: int | None = None
    status_title: str
    status_description: str
    next_action: NextAction
    reason_codes: list[str] = Field(default_factory=list)
    reason_messages: list[str] = Field(default_factory=list)
    expires_at: datetime.datetime | None = None


class StatusHistoryItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_status: ApplicationStatus | None = None
    to_status: ApplicationStatus
    actor_type: str
    reason_code: str | None = None
    comment: str | None = None
    created_at: datetime.datetime
