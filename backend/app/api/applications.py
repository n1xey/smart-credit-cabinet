"""Эндпоинты жизненного цикла заявок: создание, чтение с ETag, правка с If-Match, submit с Idempotency-Key, cancel, history."""
import datetime
import logging
import uuid

from fastapi import APIRouter, Depends, Header, Query, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.schemas.applications import (
    ApplicationInput,
    ApplicationPatch,
    ApplicationResponse,
    ApplicationSummary,
    StatusHistoryItemResponse,
)
from app.auth.deps import TokenData, require_role
from app.db import get_db
from app.enums import ActorType, ApplicationStatus, ErrorCode, Role
from app.errors import ApiError
from app.models.tables import (
    Application,
    ApplicationStatusHistory,
    Company,
    Decision,
    Product,
)
from app.services.application_service import (
    build_application_response,
    validate_application_for_submit,
)
from app.state_machine import transition

log = logging.getLogger("app.api.applications")
router = APIRouter(prefix="/applications", tags=["Applications"])


def _get_user_application(db: Session, app_id: uuid.UUID, user_id: uuid.UUID) -> Application:
    """Возвращает заявку текущего пользователя или выбрасывает 404 (сокрытие чужих данных)."""
    stmt = select(Application).where(Application.id == app_id)
    app = db.scalar(stmt)
    if app is None or app.created_by != user_id:
        raise ApiError(
            status_code=404,
            code=ErrorCode.NOT_FOUND,
            message="Заявка не найдена",
        )
    return app


@router.post("", response_model=ApplicationResponse, status_code=status.HTTP_201_CREATED)
def create_draft(
    body: ApplicationInput,
    current_user: TokenData = Depends(require_role(Role.CLIENT)),
    db: Session = Depends(get_db),
) -> ApplicationResponse:
    """Создать черновик кредитной заявки."""
    # 1. Проверка наличия компании
    comp_stmt = select(Company).where(Company.owner_id == current_user.user_id)
    company = db.scalar(comp_stmt)
    if company is None:
        raise ApiError(
            status_code=422,
            code=ErrorCode.VALIDATION_ERROR,
            message="Профиль компании не создан. Сначала заполните профиль компании",
            details=[{"field": "company", "message": "Сначала создайте профиль компании"}],
        )

    # 2. Проверка продукта
    prod_stmt = select(Product).where(Product.code == body.product_code.value)
    product = db.scalar(prod_stmt)
    if product is None:
        raise ApiError(
            status_code=422,
            code=ErrorCode.VALIDATION_ERROR,
            message=f"Неизвестный продукт '{body.product_code.value}'",
            details=[{"field": "product_code", "message": "Продукт не найден в каталоге"}],
        )

    # 3. Валидация диапазонов продукта
    if not (product.min_amount_rub <= body.amount_rub <= product.max_amount_rub):
        raise ApiError(
            status_code=422,
            code=ErrorCode.VALIDATION_ERROR,
            message=f"Сумма должна быть в диапазоне от {product.min_amount_rub:,} до {product.max_amount_rub:,} ₽",
            details=[{"field": "amount_rub", "message": f"Допустимо от {product.min_amount_rub} до {product.max_amount_rub}"}],
        )
    if not (product.min_term_months <= body.term_months <= product.max_term_months):
        raise ApiError(
            status_code=422,
            code=ErrorCode.VALIDATION_ERROR,
            message=f"Срок должен быть в диапазоне от {product.min_term_months} до {product.max_term_months} мес.",
            details=[{"field": "term_months", "message": f"Допустимо от {product.min_term_months} до {product.max_term_months}"}],
        )

    now = datetime.datetime.now(datetime.timezone.utc)
    app = Application(
        id=uuid.uuid4(),
        company_id=company.id,
        created_by=current_user.user_id,
        product_code=body.product_code.value,
        amount_rub=body.amount_rub,
        term_months=body.term_months,
        purpose=body.purpose,
        revenue_12m_rub=body.revenue_12m_rub,
        net_profit_12m_rub=body.net_profit_12m_rub,
        existing_monthly_payments_rub=body.existing_monthly_payments_rub,
        status=ApplicationStatus.DRAFT.value,
        version=1,
        created_at=now,
        updated_at=now,
    )
    db.add(app)

    history = ApplicationStatusHistory(
        id=uuid.uuid4(),
        application_id=app.id,
        from_status=None,
        to_status=ApplicationStatus.DRAFT.value,
        actor_type=ActorType.CLIENT.value,
        actor_id=str(current_user.user_id),
        reason_code="DRAFT_CREATED",
        comment="Создан черновик кредитной заявки",
        created_at=now,
    )
    db.add(history)
    db.commit()
    db.refresh(app)

    return build_application_response(app, company)


@router.get("", response_model=list[ApplicationSummary])
def list_my_applications(
    response: Response,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: TokenData = Depends(require_role(Role.CLIENT)),
    db: Session = Depends(get_db),
) -> list[ApplicationSummary]:
    """Список заявок текущего клиента."""
    if status_filter is not None and status_filter not in {s.value for s in ApplicationStatus}:
        raise ApiError(
            status_code=422,
            code=ErrorCode.VALIDATION_ERROR,
            message=f"Некорректный статус '{status_filter}'",
            details=[{"field": "status", "message": "Значение не входит в ApplicationStatus"}],
        )

    base_query = (
        select(Application, Company.name.label("company_name"))
        .join(Company, Company.id == Application.company_id)
        .where(Application.created_by == current_user.user_id)
    )

    if status_filter is not None:
        base_query = base_query.where(Application.status == status_filter)

    count_stmt = select(func.count()).select_from(base_query.subquery())
    total_count = db.scalar(count_stmt) or 0
    response.headers["X-Total-Count"] = str(total_count)

    items_stmt = base_query.order_by(Application.created_at.desc()).offset(offset).limit(limit)
    rows = db.execute(items_stmt).all()

    summaries: list[ApplicationSummary] = []
    for app, comp_name in rows:
        summaries.append(
            ApplicationSummary(
                id=app.id,
                company_name=comp_name,
                status=ApplicationStatus(app.status),
                product_code=app.product_code,
                amount_rub=app.amount_rub,
                term_months=app.term_months,
                submitted_at=app.submitted_at,
                updated_at=app.updated_at,
            )
        )
    return summaries


@router.get("/{id}", response_model=ApplicationResponse)
def get_application(
    id: uuid.UUID,
    response: Response,
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    current_user: TokenData = Depends(require_role(Role.CLIENT)),
    db: Session = Depends(get_db),
) -> ApplicationResponse | Response:
    """Получение заявки с поддержкой ETag и If-None-Match (304)."""
    app = _get_user_application(db, id, current_user.user_id)
    expected_etag = f'"{app.version}"'

    if if_none_match == expected_etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": expected_etag})

    response.headers["ETag"] = expected_etag
    company = db.scalar(select(Company).where(Company.id == app.company_id))
    decision = db.scalar(
        select(Decision).where(Decision.application_id == app.id).order_by(Decision.created_at.desc()).limit(1)
    )
    return build_application_response(app, company, decision)


@router.patch("/{id}", response_model=ApplicationResponse)
def patch_draft(
    id: uuid.UUID,
    body: ApplicationPatch,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    current_user: TokenData = Depends(require_role(Role.CLIENT)),
    db: Session = Depends(get_db),
) -> ApplicationResponse:
    """Частичное изменение черновика заявки."""
    app = _get_user_application(db, id, current_user.user_id)

    # 1. Проверка If-Match только при наличии заголовка
    if if_match is not None:
        clean_match = if_match.strip('"')
        if clean_match != str(app.version):
            raise ApiError(
                status_code=409,
                code=ErrorCode.VERSION_CONFLICT,
                message="Версия заявки изменилась (VERSION_CONFLICT)",
            )

    # 2. Статус строго DRAFT
    if app.status != ApplicationStatus.DRAFT.value:
        raise ApiError(
            status_code=409,
            code=ErrorCode.INVALID_TRANSITION,
            message="Изменение параметров доступно только в статусе DRAFT",
        )

    # 3. Валидация диапазонов продукта, если меняются сумма, срок или продукт
    target_product_code = body.product_code.value if body.product_code else app.product_code
    product = db.scalar(select(Product).where(Product.code == target_product_code))
    if product is None:
        raise ApiError(
            status_code=422,
            code=ErrorCode.VALIDATION_ERROR,
            message=f"Продукт '{target_product_code}' не найден в каталоге",
            details=[{"field": "product_code", "message": "Продукт не найден в каталоге"}],
        )

    target_amount = body.amount_rub if body.amount_rub is not None else app.amount_rub
    if target_amount is not None and not (product.min_amount_rub <= target_amount <= product.max_amount_rub):
        raise ApiError(
            status_code=422,
            code=ErrorCode.VALIDATION_ERROR,
            message=f"Сумма должна быть от {product.min_amount_rub:,} до {product.max_amount_rub:,} ₽",
            details=[{"field": "amount_rub", "message": "Сумма вне диапазона продукта"}],
        )
    target_term = body.term_months if body.term_months is not None else app.term_months
    if target_term is not None and not (product.min_term_months <= target_term <= product.max_term_months):
        raise ApiError(
            status_code=422,
            code=ErrorCode.VALIDATION_ERROR,
            message=f"Срок должен быть от {product.min_term_months} до {product.max_term_months} мес.",
            details=[{"field": "term_months", "message": "Срок вне диапазона продукта"}],
        )

    # 4. Применение обновлений
    if body.product_code is not None:
        app.product_code = body.product_code.value
    if body.amount_rub is not None:
        app.amount_rub = body.amount_rub
    if body.term_months is not None:
        app.term_months = body.term_months
    if body.purpose is not None:
        app.purpose = body.purpose
    if body.revenue_12m_rub is not None:
        app.revenue_12m_rub = body.revenue_12m_rub
    if body.net_profit_12m_rub is not None:
        app.net_profit_12m_rub = body.net_profit_12m_rub
    if body.existing_monthly_payments_rub is not None:
        app.existing_monthly_payments_rub = body.existing_monthly_payments_rub

    app.version += 1
    app.updated_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()
    db.refresh(app)

    response.headers["ETag"] = f'"{app.version}"'
    company = db.scalar(select(Company).where(Company.id == app.company_id))
    return build_application_response(app, company)


@router.post("/{id}/submit", status_code=status.HTTP_202_ACCEPTED)
def submit_application(
    id: uuid.UUID,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    current_user: TokenData = Depends(require_role(Role.CLIENT)),
    db: Session = Depends(get_db),
) -> Response:
    """Подать заявку на рассмотрение (DRAFT -> SUBMITTED)."""
    if len(idempotency_key) < 8 or len(idempotency_key) > 100:
        raise ApiError(
            status_code=422,
            code=ErrorCode.VALIDATION_ERROR,
            message="Заголовок Idempotency-Key должен содержать от 8 до 100 символов",
            details=[{"field": "Idempotency-Key", "message": "Длина ключа от 8 до 100 символов"}],
        )

    app = _get_user_application(db, id, current_user.user_id)
    company = db.scalar(select(Company).where(Company.id == app.company_id))

    # 1. Проверка идемпотентности: тот же ключ по той же заявке возвращает 202
    if app.idempotency_key == idempotency_key:
        resp_data = build_application_response(app, company)
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=resp_data.model_dump(mode="json"))

    # 2. Если заявка уже не DRAFT, а ключ другой -> 409 INVALID_TRANSITION
    if app.status != ApplicationStatus.DRAFT.value:
        raise ApiError(
            status_code=409,
            code=ErrorCode.INVALID_TRANSITION,
            message="Заявка уже отправлена на проверку и не может быть подана повторно",
        )

    # 3. Проверка использования ключа другой заявкой -> 409 IDEMPOTENCY_CONFLICT
    conflict_stmt = select(Application).where(
        Application.idempotency_key == idempotency_key,
        Application.id != app.id,
    )
    if db.scalar(conflict_stmt) is not None:
        raise ApiError(
            status_code=409,
            code=ErrorCode.IDEMPOTENCY_CONFLICT,
            message="Idempotency-Key уже использован для другой заявки",
        )

    # 4. Валидация полноты параметров заявки
    product = db.scalar(select(Product).where(Product.code == app.product_code))
    if product is None:
        raise ApiError(
            status_code=422,
            code=ErrorCode.VALIDATION_ERROR,
            message="Продукт заявки не найден в каталоге",
        )
    validate_application_for_submit(app, company, product)

    app.idempotency_key = idempotency_key

    # 5. Вызов автомата состояний в транзакции
    try:
        transition(
            session=db,
            application=app,
            to_status=ApplicationStatus.SUBMITTED,
            actor_type=ActorType.CLIENT,
            actor_id=str(current_user.user_id),
            actor_role="CLIENT",
            reason_code="CLIENT_SUBMITTED",
            comment="Заявка подана клиентом через личный кабинет",
        )
        db.commit()
        db.refresh(app)
    except IntegrityError:
        db.rollback()
        # Проверяем причину ошибки целостности (на случай параллельного запроса)
        recheck = db.scalar(select(Application).where(Application.id == app.id))
        if recheck and recheck.idempotency_key == idempotency_key:
            resp_data = build_application_response(recheck, company)
            return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=resp_data.model_dump(mode="json"))
        raise ApiError(
            status_code=409,
            code=ErrorCode.IDEMPOTENCY_CONFLICT,
            message="Конфликт ключа идемпотентности при параллельной обработке",
        )

    resp_data = build_application_response(app, company)
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=resp_data.model_dump(mode="json"))


@router.post("/{id}/cancel", response_model=ApplicationResponse)
def cancel_application(
    id: uuid.UUID,
    current_user: TokenData = Depends(require_role(Role.CLIENT)),
    db: Session = Depends(get_db),
) -> ApplicationResponse:
    """Отменить заявку клиентом (допустимо из DRAFT, NEEDS_INFO, OFFER, COUNTER_OFFER)."""
    app = _get_user_application(db, id, current_user.user_id)
    transition(
        session=db,
        application=app,
        to_status=ApplicationStatus.CANCELLED,
        actor_type=ActorType.CLIENT,
        actor_id=str(current_user.user_id),
        actor_role="CLIENT",
        reason_code="CLIENT_CANCELLED",
        comment="Заявка отменена клиентом",
    )
    db.commit()
    db.refresh(app)

    company = db.scalar(select(Company).where(Company.id == app.company_id))
    return build_application_response(app, company)


@router.get("/{id}/history", response_model=list[StatusHistoryItemResponse])
def get_application_history(
    id: uuid.UUID,
    current_user: TokenData = Depends(require_role(Role.CLIENT)),
    db: Session = Depends(get_db),
) -> list[ApplicationStatusHistory]:
    """Таймлайн истории статусов заявки."""
    app = _get_user_application(db, id, current_user.user_id)
    stmt = (
        select(ApplicationStatusHistory)
        .where(ApplicationStatusHistory.application_id == app.id)
        .order_by(ApplicationStatusHistory.created_at.asc())
    )
    history = list(db.scalars(stmt).all())
    return history
