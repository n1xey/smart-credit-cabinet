"""Pydantic-схемы для каталога продуктов и рекомендаций."""
from pydantic import BaseModel, ConfigDict, Field

from app.enums import DocType, ProductCode, RecommendPurpose


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: ProductCode
    name: str
    description: str | None = None
    min_amount_rub: int
    max_amount_rub: int
    min_term_months: int
    max_term_months: int
    base_rate_percent: float
    auto_limit_rub: int
    min_business_age_months: int = 0
    required_documents: list[DocType] = Field(default_factory=list)


class RecommendRequest(BaseModel):
    purpose: RecommendPurpose
    amount_rub: int | None = Field(default=None, ge=1)
    free_text: str | None = Field(default=None, max_length=500)


class RecommendResponse(BaseModel):
    product_code: str
    explanation: str
    source: str = "RULES"
