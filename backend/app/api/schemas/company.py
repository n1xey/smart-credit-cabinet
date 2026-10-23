"""Pydantic-схемы для профиля компании."""
import datetime
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.enums import LegalForm


class CompanyInput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    inn: str = Field(..., pattern=r"^\d{10}(\d{2})?$", description="ИНН 10 цифр для ООО или 12 для ИП")
    name: str = Field(..., min_length=1, description="Наименование компании или ФИО ИП")
    legal_form: LegalForm
    registration_date: datetime.date | None = None
    okved: str | None = Field(default=None, examples=["62.01"])
    address: str | None = None


class CompanyResponse(CompanyInput):
    id: uuid.UUID
