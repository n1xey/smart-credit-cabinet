"""API для офферов, запросов уточнений (InfoRequest) и подписания документов."""
import datetime
import uuid

from fastapi import APIRouter, Depends, Header
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas.applications import ApplicationResponse
from app.api.schemas.offers import (
    CorrectedFieldsSchema,
    InfoRequestResponse,
    InfoResponseInput,
    OfferResponse,
)
from app.auth.deps import TokenData, require_role
from app.db import get_db
from app.enums import ActorType, ApplicationStatus, ErrorCode, Role
from app.errors import ApiError
from app.models.tables import Application, Company, InfoRequest, Offer, Product
from app.services.application_service import build_application_response
from app.state_machine.machine import transition

router = APIRouter(prefix="/applications")

_ALLOWED_APP_FIELDS = {
    "amount_rub",
    "term_months",
    "purpose",
    "revenue_12m_rub",
    "net_profit_12m_rub",
    "existing_monthly_payments_rub",
}
_ALLOWED_COMPANY_FIELDS = {
    "name",
    "okved",
    "address",
    "registration_date",
}


def _get_client_application(db: Session, app_id: uuid.UUID, user_id: uuid.UUID) -> Application:
    """Возвращает заявку текущего клиента или 404 NOT_FOUND."""
    app = db.scalar(select(Application).where(Application.id == app_id))
    if app is None or app.created_by != user_id:
        raise ApiError(
            status_code=404,
            code=ErrorCode.NOT_FOUND,
            message="Заявка не существует или принадлежит другому клиенту",
        )
    return app


@router.get("/{id}/info-request", response_model=InfoRequestResponse, tags=["Applications"])
def get_info_request(
    id: uuid.UUID,
    current_user: TokenData = Depends(require_role(Role.CLIENT)),
    db: Session = Depends(get_db),
) -> InfoRequestResponse:
    """Актуальный запрос уточнений (статус NEEDS_INFO)."""
    app = _get_client_application(db, id, current_user.user_id)

    if app.status != ApplicationStatus.NEEDS_INFO.value:
        raise ApiError(
            status_code=404,
            code=ErrorCode.NOT_FOUND,
            message="Запрос уточнений не найден или заявка не требует уточнений",
        )

    info_req = db.scalar(
        select(InfoRequest)
        .where(InfoRequest.application_id == app.id, InfoRequest.answered_at.is_(None))
        .order_by(InfoRequest.round.desc())
    )
    if info_req is None:
        raise ApiError(
            status_code=404,
            code=ErrorCode.NOT_FOUND,
            message="Актуальный запрос уточнений не найден",
        )
    return InfoRequestResponse.model_validate(info_req)


@router.post("/{id}/info-request", response_model=ApplicationResponse, tags=["Applications"])
def answer_info_request(
    id: uuid.UUID,
    body: InfoResponseInput,
    current_user: TokenData = Depends(require_role(Role.CLIENT)),
    db: Session = Depends(get_db),
) -> ApplicationResponse:
    """Ответить на запрос уточнений (NEEDS_INFO -> DATA_CHECK)."""
    app = _get_client_application(db, id, current_user.user_id)

    if app.status != ApplicationStatus.NEEDS_INFO.value:
        raise ApiError(
            status_code=409,
            code=ErrorCode.INVALID_TRANSITION,
            message=f"Ответ на запрос уточнений недопустим в статусе {app.status}. Разрешено только в NEEDS_INFO",
        )

    info_req = db.scalar(
        select(InfoRequest)
        .where(InfoRequest.application_id == app.id, InfoRequest.answered_at.is_(None))
        .order_by(InfoRequest.round.desc())
    )
    if info_req is None:
        raise ApiError(
            status_code=404,
            code=ErrorCode.NOT_FOUND,
            message="Актуальный запрос уточнений не найден",
        )

    # 1. Валидация corrected_fields через строгую Pydantic-схему (extra='forbid')
    parsed_corrections: CorrectedFieldsSchema | None = None
    if body.corrected_fields is not None:
        try:
            parsed_corrections = CorrectedFieldsSchema.model_validate(body.corrected_fields)
        except ValidationError as err:
            details = [
                {
                    "field": f"corrected_fields.{'.'.join(str(p) for p in e['loc'])}",
                    "message": e["msg"],
                }
                for e in err.errors()
            ]
            raise ApiError(
                status_code=422,
                code=ErrorCode.VALIDATION_ERROR,
                message="Ошибка валидации corrected_fields",
                details=details,
            )

    # 2. Бизнес-валидация диапазонов продукта и возраста компании
    product = db.scalar(select(Product).where(Product.code == app.product_code))
    company = db.scalar(select(Company).where(Company.id == app.company_id))

    if parsed_corrections is not None:
        if product is not None:
            target_amount = (
                parsed_corrections.amount_rub
                if parsed_corrections.amount_rub is not None
                else app.amount_rub
            )
            if target_amount is not None and not (
                product.min_amount_rub <= target_amount <= product.max_amount_rub
            ):
                raise ApiError(
                    status_code=422,
                    code=ErrorCode.VALIDATION_ERROR,
                    message=f"Сумма должна быть в диапазоне от {product.min_amount_rub:,} до {product.max_amount_rub:,} ₽",
                    details=[
                        {
                            "field": "corrected_fields.amount_rub",
                            "message": f"Допустимо от {product.min_amount_rub} до {product.max_amount_rub}",
                        }
                    ],
                )

            target_term = (
                parsed_corrections.term_months
                if parsed_corrections.term_months is not None
                else app.term_months
            )
            if target_term is not None and not (
                product.min_term_months <= target_term <= product.max_term_months
            ):
                raise ApiError(
                    status_code=422,
                    code=ErrorCode.VALIDATION_ERROR,
                    message=f"Срок должен быть в диапазоне от {product.min_term_months} до {product.max_term_months} мес.",
                    details=[
                        {
                            "field": "corrected_fields.term_months",
                            "message": f"Допустимо от {product.min_term_months} до {product.max_term_months}",
                        }
                    ],
                )

        # Проверка возраста бизнеса при изменении registration_date
        target_reg = parsed_corrections.registration_date or (
            company.registration_date if company else None
        )
        if target_reg is not None and product and product.min_business_age_months > 0:
            today = datetime.date.today()
            age_months = (today.year - target_reg.year) * 12 + (today.month - target_reg.month)
            if age_months < product.min_business_age_months:
                raise ApiError(
                    status_code=422,
                    code=ErrorCode.VALIDATION_ERROR,
                    message=(
                        f"Продукт '{product.code}' доступен при возрасте бизнеса от "
                        f"{product.min_business_age_months} мес. (текущий: {age_months} мес.)"
                    ),
                    details=[
                        {
                            "field": "corrected_fields.registration_date",
                            "message": "Возраст бизнеса меньше минимального",
                        }
                    ],
                )

    # 3. Транзакционное применение исправлений и переход состояния
    try:
        if parsed_corrections is not None:
            data_to_update = parsed_corrections.model_dump(exclude_unset=True)
            for field_name, val in data_to_update.items():
                if field_name in _ALLOWED_APP_FIELDS:
                    setattr(app, field_name, val)
                elif field_name in _ALLOWED_COMPANY_FIELDS and company:
                    setattr(company, field_name, val)

        # Сохранение ответа в info_requests
        info_req.response = body.model_dump()
        info_req.answered_at = datetime.datetime.now(datetime.timezone.utc)

        # Переход в DATA_CHECK через автомат состояний
        transition(
            session=db,
            application=app,
            to_status=ApplicationStatus.DATA_CHECK,
            actor_type=ActorType.CLIENT,
            actor_id=str(current_user.user_id),
            actor_role="CLIENT",
            reason_code="CLIENT_ANSWERED_INFO",
            comment=body.comment or "Клиент предоставил ответ на запрос уточнений",
        )
        db.commit()
        db.refresh(app)
    except Exception:
        db.rollback()
        raise

    return build_application_response(app, company)


@router.get("/{id}/offer", response_model=OfferResponse, tags=["Offer"])
def get_offer(
    id: uuid.UUID,
    current_user: TokenData = Depends(require_role(Role.CLIENT)),
    db: Session = Depends(get_db),
) -> OfferResponse:
    """Актуальное кредитное предложение (OFFER или COUNTER_OFFER)."""
    app = _get_client_application(db, id, current_user.user_id)

    # По контракту оффер доступен только в статусах OFFER или COUNTER_OFFER
    if app.status not in (ApplicationStatus.OFFER.value, ApplicationStatus.COUNTER_OFFER.value):
        raise ApiError(
            status_code=404,
            code=ErrorCode.NOT_FOUND,
            message="Активное предложение не найдено для заявки в текущем статусе",
        )

    offer = db.scalar(
        select(Offer).where(Offer.application_id == app.id, Offer.state == "ACTIVE")
    )
    if offer is None:
        raise ApiError(
            status_code=404,
            code=ErrorCode.NOT_FOUND,
            message="Активное предложение не найдено",
        )

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    valid_until = offer.valid_until
    if valid_until.tzinfo is None:
        valid_until = valid_until.replace(tzinfo=datetime.timezone.utc)
    if valid_until < now_utc:
        raise ApiError(
            status_code=404,
            code=ErrorCode.NOT_FOUND,
            message="Срок действия кредитного предложения истёк",
        )
    return OfferResponse.model_validate(offer)


@router.post("/{id}/offer/accept", response_model=ApplicationResponse, tags=["Offer"])
def accept_offer(
    id: uuid.UUID,
    if_match: str | None = Header(default=None, alias="If-Match"),
    current_user: TokenData = Depends(require_role(Role.CLIENT)),
    db: Session = Depends(get_db),
) -> ApplicationResponse:
    """Принять предложение (OFFER/COUNTER_OFFER -> ACCEPTED, актор CLIENT)."""
    app = _get_client_application(db, id, current_user.user_id)

    # 1. Проверка If-Match при наличии заголовка
    if if_match is not None:
        expected_tag = f'"{app.version}"'
        cleaned = if_match.strip()
        if cleaned != expected_tag and cleaned != str(app.version):
            raise ApiError(
                status_code=409,
                code=ErrorCode.VERSION_CONFLICT,
                message=f"Конфликт версий: текущая версия {app.version}, указана {if_match}",
            )

    # 2. Проверка статуса
    if app.status not in (ApplicationStatus.OFFER.value, ApplicationStatus.COUNTER_OFFER.value):
        raise ApiError(
            status_code=409,
            code=ErrorCode.INVALID_TRANSITION,
            message=f"Принятие предложения недопустимо в статусе {app.status}. Ожидается OFFER или COUNTER_OFFER",
        )

    # 3. Проверка активного предложения и срока действия
    offer = db.scalar(
        select(Offer).where(Offer.application_id == app.id, Offer.state == "ACTIVE")
    )
    if offer is None:
        raise ApiError(
            status_code=409,
            code=ErrorCode.INVALID_TRANSITION,
            message="Активное кредитное предложение не найдено",
        )

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    valid_until = offer.valid_until
    if valid_until.tzinfo is None:
        valid_until = valid_until.replace(tzinfo=datetime.timezone.utc)
    if valid_until < now_utc:
        raise ApiError(
            status_code=409,
            code=ErrorCode.INVALID_TRANSITION,
            message="Срок действия кредитного предложения истёк",
        )

    # 4. Переход в ACCEPTED в защищенной транзакции
    try:
        transition(
            session=db,
            application=app,
            to_status=ApplicationStatus.ACCEPTED,
            actor_type=ActorType.CLIENT,
            actor_id=str(current_user.user_id),
            actor_role="CLIENT",
            reason_code="CLIENT_ACCEPTED",
            comment="Клиент принял условия предложения",
        )
        db.commit()
        db.refresh(app)
    except Exception:
        db.rollback()
        raise

    company = db.scalar(select(Company).where(Company.id == app.company_id))
    return build_application_response(app, company)


@router.post("/{id}/offer/decline", response_model=ApplicationResponse, tags=["Offer"])
def decline_offer(
    id: uuid.UUID,
    if_match: str | None = Header(default=None, alias="If-Match"),
    current_user: TokenData = Depends(require_role(Role.CLIENT)),
    db: Session = Depends(get_db),
) -> ApplicationResponse:
    """Отказаться от предложения (-> CANCELLED)."""
    app = _get_client_application(db, id, current_user.user_id)

    # 1. Проверка If-Match при наличии заголовка
    if if_match is not None:
        expected_tag = f'"{app.version}"'
        cleaned = if_match.strip()
        if cleaned != expected_tag and cleaned != str(app.version):
            raise ApiError(
                status_code=409,
                code=ErrorCode.VERSION_CONFLICT,
                message=f"Конфликт версий: текущая версия {app.version}, указана {if_match}",
            )

    # 2. Проверка статуса
    if app.status not in (ApplicationStatus.OFFER.value, ApplicationStatus.COUNTER_OFFER.value):
        raise ApiError(
            status_code=409,
            code=ErrorCode.INVALID_TRANSITION,
            message=f"Отклонение предложения недопустимо в статусе {app.status}. Ожидается OFFER или COUNTER_OFFER",
        )

    # 3. Проверка активного предложения и срока действия
    offer = db.scalar(
        select(Offer).where(Offer.application_id == app.id, Offer.state == "ACTIVE")
    )
    if offer is None:
        raise ApiError(
            status_code=409,
            code=ErrorCode.INVALID_TRANSITION,
            message="Активное кредитное предложение не найдено",
        )

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    valid_until = offer.valid_until
    if valid_until.tzinfo is None:
        valid_until = valid_until.replace(tzinfo=datetime.timezone.utc)
    if valid_until < now_utc:
        raise ApiError(
            status_code=409,
            code=ErrorCode.INVALID_TRANSITION,
            message="Срок действия кредитного предложения истёк",
        )

    # 4. Переход в CANCELLED в транзакции
    try:
        transition(
            session=db,
            application=app,
            to_status=ApplicationStatus.CANCELLED,
            actor_type=ActorType.CLIENT,
            actor_id=str(current_user.user_id),
            actor_role="CLIENT",
            reason_code="OFFER_DECLINED",
            comment="Клиент отказался от кредитного предложения",
        )
        db.commit()
        db.refresh(app)
    except Exception:
        db.rollback()
        raise

    company = db.scalar(select(Company).where(Company.id == app.company_id))
    return build_application_response(app, company)


@router.post("/{id}/sign", response_model=ApplicationResponse, tags=["Offer"])
def sign_application(
    id: uuid.UUID,
    current_user: TokenData = Depends(require_role(Role.CLIENT)),
    db: Session = Depends(get_db),
) -> ApplicationResponse:
    """«Подписать» документы (имитация; SIGNING -> DISBURSED, актор CLIENT; допустимо только в SIGNING)."""
    app = _get_client_application(db, id, current_user.user_id)

    if app.status != ApplicationStatus.SIGNING.value:
        raise ApiError(
            status_code=409,
            code=ErrorCode.INVALID_TRANSITION,
            message=f"Подписание документов недопустимо в статусе {app.status}. Разрешено только в статусе SIGNING",
        )

    try:
        transition(
            session=db,
            application=app,
            to_status=ApplicationStatus.DISBURSED,
            actor_type=ActorType.CLIENT,
            actor_id=str(current_user.user_id),
            actor_role="CLIENT",
            reason_code="CLIENT_SIGNED",
            comment="Клиент подтвердил подписание кредитной документации",
        )
        db.commit()
        db.refresh(app)
    except Exception:
        db.rollback()
        raise

    company = db.scalar(select(Company).where(Company.id == app.company_id))
    return build_application_response(app, company)
