"""Эндпоинты каталога продуктов: /products, /products/recommend."""
import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas.catalog import ProductResponse, RecommendRequest, RecommendResponse
from app.auth.deps import TokenData, get_current_user
from app.db import get_db
from app.enums import ProductCode, RecommendPurpose
from app.models.tables import Product

log = logging.getLogger("app.api.products")
router = APIRouter(prefix="/products", tags=["Catalog"])


@router.get("", response_model=list[ProductResponse])
def list_products(db: Session = Depends(get_db)) -> list[Product]:
    """Список кредитных продуктов (публичный эндпоинт)."""
    stmt = select(Product).order_by(Product.code)
    products = list(db.scalars(stmt).all())
    return products


@router.post("/recommend", response_model=RecommendResponse)
def recommend_product(
    body: RecommendRequest,
    current_user: TokenData = Depends(get_current_user),
) -> RecommendResponse:
    """Подбор продукта по детерминированным правилам."""
    if body.purpose == RecommendPurpose.EQUIPMENT:
        product_code = ProductCode.EQUIPMENT.value
        explanation = "Кредит на оборудование: приобретение оборудования и модернизация основных средств"
    elif (
        body.purpose == RecommendPurpose.URGENT_CASH
        and body.amount_rub is not None
        and 100_000 <= body.amount_rub <= 1_500_000
    ):
        product_code = ProductCode.EXPRESS.value
        explanation = "Экспресс-кредит: быстрое решение без залога до 1,5 млн руб."
    else:
        product_code = ProductCode.WORKING_CAPITAL.value
        explanation = "Оборотный кредит: пополнение оборотных средств, закупка товаров и сырья"

    return RecommendResponse(
        product_code=product_code,
        explanation=explanation,
        source="RULES",
    )
