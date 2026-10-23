"""API для офферов, запросов уточнений (InfoRequest) и подписания документов."""
import datetime
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas.applications import ApplicationResponse
from app.api.schemas.offers import InfoRequestResponse, InfoResponseInput, OfferResponse
from app.auth.deps import TokenData, require_role
from app.db import get_db
from app.enums import ActorType, ApplicationStatus, ErrorCode, Role
from app.errors import ApiError
from app.models.tables import Application, Company, InfoRequest, Offer
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
_ALL_ALLOWED_CORRECTED_FIELDS = _ALLOWED_APP_FIELDS | _ALLOWED_COMPANY_FIELDS


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

    # Валидация corrected_fields по строгому белому списку
    corrected = body.corrected_fields or {}
    for key, val in corrected.items():
        if key not in _ALL_ALLOWED_CORRECTED_FIELDS:
            raise ApiError(
                status_code=422,
                code=ErrorCode.VALIDATION_ERROR,
                message=f"Поле '{key}' не разрешено для корректировки",
                details=[{"field": f"corrected_fields.{key}", "message": "Поле вне белого списка"}],
            )
        # Валидация типов
        if key in ("amount_rub", "term_months"):
            if not isinstance(val, int) or val <= 0:
                raise ApiError(
                    status_code=422,
                    code=ErrorCode.VALIDATION_ERROR,
                    message=f"Поле '{key}' должно быть положительным целым числом",
                    details=[{"field": f"corrected_fields.{key}", "message": "Ожидается положительное целое число"}],
                )
        elif key in ("revenue_12m_rub", "net_profit_12m_rub", "existing_monthly_payments_rub"):
            if val is not None and not isinstance(val, int):
                raise ApiError(
                    status_code=422,
                    code=ErrorCode.VALIDATION_ERROR,
                    message=f"Поле '{key}' должно быть целым числом",
                    details=[{"field": f"corrected_fields.{key}", "message": "Ожидается целое число"}],
                )

    # Применение исправлений
    company = db.scalar(select(Company).where(Company.id == app.company_id))
    for key, val in corrected.items():
        if key in _ALLOWED_APP_FIELDS:
            setattr(app, key, val)
        elif key in _ALLOWED_COMPANY_FIELDS and company:
            if key == "registration_date" and isinstance(val, str):
                try:
                    val = datetime.date.fromisoformat(val)
                except ValueError:
                    raise ApiError(
                        status_code=422,
                        code=ErrorCode.VALIDATION_ERROR,
                        message="Неверный формат даты registration_date (ожидается ГГГГ-ММ-ДД)",
                        details=[{"field": "corrected_fields.registration_date", "message": "Формат YYYY-MM-DD"}],
                    )
            setattr(company, key, val)

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
    return build_application_response(app, company)


@router.get("/{id}/offer", response_model=OfferResponse, tags=["Offer"])
def get_offer(
    id: uuid.UUID,
    current_user: TokenData = Depends(require_role(Role.CLIENT)),
    db: Session = Depends(get_db),
) -> OfferResponse:
    """Актуальное кредитное предложение (OFFER или COUNTER_OFFER)."""
    app = _get_client_application(db, id, current_user.user_id)

    offer = db.scalar(
        select(Offer).where(Offer.application_id == app.id, Offer.state == "ACTIVE")
    )
    if offer is None:
        raise ApiError(
            status_code=404,
            code=ErrorCode.NOT_FOUND,
            message="Активное предложение не найдено",
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

    # 4. Переход в ACCEPTED
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

    # 3. Переход в CANCELLED
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
    company = db.scalar(select(Company).where(Company.id == app.company_id))
    return build_application_response(app, company)
