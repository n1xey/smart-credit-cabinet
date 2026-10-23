"""Ядро автомата состояний кредитного конвейера.

Единая точка входа для смены статусов заявок:
- transition(...)
- take_in_review(...)
- get_allowed_transitions(...)
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.enums import ActorType, ApplicationStatus, ErrorCode, OfferState, Role
from app.errors import ApiError
from app.models.tables import Application, ApplicationStatusHistory, Offer
from app.state_machine.guards import (
    should_escalate_info_rounds,
    validate_optimistic_lock,
    validate_ownership_and_actor,
    validate_terminal_status,
)
from app.state_machine.jobs import enqueue_transition_job
from app.state_machine.transitions import (
    SYSTEM_TARGET_STATUSES,
    TERMINAL_STATUSES,
    get_allowed_targets,
    get_transition_rule,
)

log = logging.getLogger("app.state_machine")


def transition(
    session: Session,
    application: Application,
    to_status: ApplicationStatus | str,
    actor_type: ActorType | str,
    actor_id: str | uuid.UUID | None = None,
    actor_role: str | None = None,
    reason_code: str | None = None,
    comment: str | None = None,
    payload: dict | None = None,
    expected_version: int | None = None,
    idempotent: bool = True,
    enqueue_jobs: bool = True,
) -> Application:
    """Выполняет атомарный переход заявки в новый статус.

    Гарантии:
    1. Проверка допустимости перехода по графу docs/STATE_MACHINE.md
    2. Проверка прав и принадлежности заявки актору
    3. Оптимистичная блокировка (version / If-Match)
    4. Запись строки аудита в application_status_history в той же транзакции
    5. Автоматический расчёт expires_at и submitted_at
    6. Инкремент info_rounds и эскалация в MANUAL_REVIEW при превышении MAX_INFO_ROUNDS
    7. Синхронизация статуса активного оффера (ACCEPTED, DECLINED, EXPIRED)
    8. Постановка соответствующей задачи в очередь jobs
    9. Идемпотентность повторных вызовов системного воркера
    """
    settings = get_settings()
    now_utc = datetime.now(timezone.utc)

    # Нормализация входных перечислений
    target_status = ApplicationStatus(to_status) if isinstance(to_status, str) else to_status
    normalized_actor = ActorType(actor_type) if isinstance(actor_type, str) else actor_type
    # 1. Блокировка строки на уровне БД (SELECT ... FOR UPDATE) для предотвращения гонок
    if application.id is not None:
        locked_app = (
            session.query(Application)
            .filter(Application.id == application.id)
            .with_for_update()
            .first()
        )
        if locked_app is not None:
            application = locked_app

    current_status = ApplicationStatus(application.status)

    # 2. Проверка терминального статуса: из финальных статусов переходы запрещены
    validate_terminal_status(application)

    # 3. Проверка оптимистичной блокировки (If-Match) ДО любого раннего возврата
    validate_optimistic_lock(application, expected_version)

    # 4. Идемпотентность воркера: подтверждённый повтор легитимного системного шага
    if current_status == target_status and normalized_actor == ActorType.SYSTEM and idempotent:
        if target_status not in SYSTEM_TARGET_STATUSES:
            raise ApiError(
                status_code=409,
                code=ErrorCode.INVALID_TRANSITION,
                message=f"Системный переход в статус '{target_status.value}' не предусмотрен графом",
            )
        log.info(
            "state_machine.idempotent_skip",
            extra={
                "application_id": str(application.id),
                "status": current_status.value,
                "actor_type": normalized_actor.value,
            },
        )
        return application

    # 4. Проверка лимита раундов уточнений (MAX_INFO_ROUNDS -> MANUAL_REVIEW)
    effective_target_status = target_status
    effective_reason_code = reason_code
    effective_comment = comment
    is_escalated = should_escalate_info_rounds(application, target_status, settings.max_info_rounds)

    if is_escalated:
        effective_target_status = ApplicationStatus.MANUAL_REVIEW
        effective_reason_code = "INFO_ROUNDS_EXCEEDED"
        effective_comment = comment or "Превышен лимит раундов уточнений (передано оператору)"
        log.warning(
            "state_machine.info_rounds_exceeded",
            extra={
                "application_id": str(application.id),
                "info_rounds": application.info_rounds,
                "max_info_rounds": settings.max_info_rounds,
            },
        )

    # 5. Проверка прав актора и валидности перехода
    validate_ownership_and_actor(
        application=application,
        target_status=effective_target_status,
        actor_type=normalized_actor,
        actor_id=actor_id,
        actor_role=actor_role,
        is_escalated=is_escalated,
    )

    # 6. Обновление полей жизненного цикла заявки
    old_status = application.status

    if effective_target_status == ApplicationStatus.SUBMITTED and not application.submitted_at:
        application.submitted_at = now_utc

    if effective_target_status == ApplicationStatus.NEEDS_INFO:
        application.info_rounds += 1
        application.expires_at = now_utc + timedelta(hours=settings.needs_info_ttl_hours)
    elif effective_target_status in (ApplicationStatus.OFFER, ApplicationStatus.COUNTER_OFFER):
        # Если в payload передан valid_until или есть активный оффер
        offer_valid_until = None
        if payload and "valid_until" in payload:
            raw_vu = payload["valid_until"]
            offer_valid_until = datetime.fromisoformat(raw_vu) if isinstance(raw_vu, str) else raw_vu
        else:
            active_offer = (
                session.query(Offer)
                .filter(
                    Offer.application_id == application.id,
                    Offer.state == OfferState.ACTIVE.value,
                )
                .first()
            )
            if active_offer and active_offer.valid_until:
                offer_valid_until = active_offer.valid_until

        application.expires_at = offer_valid_until or (now_utc + timedelta(hours=settings.offer_ttl_hours))
    elif effective_target_status == ApplicationStatus.SIGNING:
        application.expires_at = now_utc + timedelta(hours=settings.signing_ttl_hours)
    else:
        application.expires_at = None

    # 7. Синхронизация статуса активных офферов
    if effective_target_status == ApplicationStatus.ACCEPTED:
        _update_active_offers_state(session, application.id, OfferState.ACCEPTED)
    elif effective_target_status == ApplicationStatus.CANCELLED and current_status in (
        ApplicationStatus.OFFER,
        ApplicationStatus.COUNTER_OFFER,
    ):
        _update_active_offers_state(session, application.id, OfferState.DECLINED)
    elif effective_target_status == ApplicationStatus.EXPIRED and current_status in (
        ApplicationStatus.OFFER,
        ApplicationStatus.COUNTER_OFFER,
    ):
        _update_active_offers_state(session, application.id, OfferState.EXPIRED)

    # 8. Изменение статуса и версионирование
    application.status = effective_target_status.value
    application.version += 1
    application.updated_at = now_utc

    # 9. Запись аудита в application_status_history
    history = ApplicationStatusHistory(
        application_id=application.id,
        from_status=old_status,
        to_status=effective_target_status.value,
        actor_type=normalized_actor.value,
        actor_id=str(actor_id) if actor_id else None,
        reason_code=effective_reason_code,
        comment=effective_comment,
        created_at=now_utc,
    )
    session.add(history)

    # 10. Постановка фоновой задачи в очередь jobs
    if enqueue_jobs:
        enqueue_transition_job(session, application, effective_target_status)

    session.flush()

    log.info(
        "state_machine.transition_success",
        extra={
            "application_id": str(application.id),
            "from_status": old_status,
            "to_status": effective_target_status.value,
            "actor_type": normalized_actor.value,
            "version": application.version,
        },
    )

    return application


def take_in_review(
    session: Session,
    application: Application,
    operator_id: str | uuid.UUID,
    operator_role: str = Role.OPERATOR.value,
    expected_version: int | None = None,
) -> Application:
    """Назначает оператора на заявку в статусе MANUAL_REVIEW (take).

    Статус заявки остаётся MANUAL_REVIEW. В историю пишется запись с reason_code="TAKEN".
    Если заявка уже взята другим оператором, выбрасывается 409 CONFLICT.
    Повторное взятие тем же оператором идемпотентно.
    """
    # 0. Блокировка строки на уровне БД (SELECT ... FOR UPDATE) для предотвращения гонок
    if application.id is not None:
        locked_app = (
            session.query(Application)
            .filter(Application.id == application.id)
            .with_for_update()
            .first()
        )
        if locked_app is not None:
            application = locked_app

    # 1. Проверка роли оператора
    if operator_role not in (Role.OPERATOR.value, Role.ADMIN.value):
        raise ApiError(
            status_code=403,
            code=ErrorCode.FORBIDDEN,
            message="Взять заявку в работу может только оператор или администратор",
        )

    # 2. Проверка статуса: только MANUAL_REVIEW
    if application.status != ApplicationStatus.MANUAL_REVIEW.value:
        raise ApiError(
            status_code=409,
            code=ErrorCode.INVALID_TRANSITION,
            message=f"Взять в работу можно только заявку в статусе MANUAL_REVIEW (текущий: '{application.status}')",
        )

    # 3. Проверка оптимистичной блокировки (If-Match) ДО любого возврата
    validate_optimistic_lock(application, expected_version)

    # 4. Проверка назначения на другого оператора
    op_uuid = uuid.UUID(str(operator_id)) if isinstance(operator_id, str) else operator_id
    if application.assigned_operator_id is not None:
        if application.assigned_operator_id != op_uuid:
            raise ApiError(
                status_code=409,
                code=ErrorCode.CONFLICT,
                message="Заявка уже взята в работу другим оператором",
            )
        # Идемпотентный возврат, если уже назначена этому оператору (версия проверена)
        return application

    # 5. Назначение и версионирование
    now_utc = datetime.now(timezone.utc)
    application.assigned_operator_id = op_uuid
    application.version += 1
    application.updated_at = now_utc

    # 6. Запись в историю: from_status = to_status = MANUAL_REVIEW, reason_code = TAKEN
    history = ApplicationStatusHistory(
        application_id=application.id,
        from_status=ApplicationStatus.MANUAL_REVIEW.value,
        to_status=ApplicationStatus.MANUAL_REVIEW.value,
        actor_type=ActorType.OPERATOR.value,
        actor_id=str(operator_id),
        reason_code="TAKEN",
        comment="Заявка взята в работу оператором",
        created_at=now_utc,
    )
    session.add(history)
    session.flush()

    log.info(
        "state_machine.take_success",
        extra={
            "application_id": str(application.id),
            "operator_id": str(operator_id),
            "version": application.version,
        },
    )

    return application


def get_allowed_transitions(
    application: Application,
    actor_type: ActorType | str,
    actor_id: str | uuid.UUID | None = None,
    actor_role: str | None = None,
) -> list[ApplicationStatus]:
    """Возвращает список целевых статусов, в которые данный актор может перевести заявку."""
    current_status = ApplicationStatus(application.status)
    if current_status in TERMINAL_STATUSES:
        return []

    normalized_actor = ActorType(actor_type) if isinstance(actor_type, str) else actor_type

    # 1. Проверка роли пользователя
    if normalized_actor == ActorType.CLIENT:
        if actor_role is not None and actor_role != Role.CLIENT.value:
            return []
        if actor_id is None or str(application.created_by) != str(actor_id):
            return []
    elif normalized_actor == ActorType.OPERATOR:
        if actor_role is not None and actor_role not in (Role.OPERATOR.value, Role.ADMIN.value):
            return []
        # Для оператора на MANUAL_REVIEW проверяем назначение
        if current_status == ApplicationStatus.MANUAL_REVIEW:
            if application.assigned_operator_id is None:
                return []
            if str(application.assigned_operator_id) != str(actor_id):
                return []
    elif normalized_actor == ActorType.SYSTEM:
        if actor_role is not None:
            return []

    return get_allowed_targets(current_status, normalized_actor)


def _update_active_offers_state(
    session: Session,
    application_id: uuid.UUID,
    new_state: OfferState,
) -> None:
    """Обновляет состояние всех активных предложений по заявке."""
    offers = (
        session.query(Offer)
        .filter(
            Offer.application_id == application_id,
            Offer.state == OfferState.ACTIVE.value,
        )
        .all()
    )
    for offer in offers:
        offer.state = new_state.value
