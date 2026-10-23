"""Охранные проверки (guards) для автомата состояний.

Проверяют:
1. Терминальные статусы
2. Существование перехода в графе
3. Оптимистичную блокировку (version)
4. Права и принадлежность заявки актору (CLIENT / OPERATOR / SYSTEM)
5. Назначение оператора на заявку (MANUAL_REVIEW)
6. Превышение лимита раундов уточнений (MAX_INFO_ROUNDS)
"""
import uuid
from typing import Any

from app.enums import ActorType, ApplicationStatus, ErrorCode, Role
from app.errors import ApiError
from app.models.tables import Application
from app.state_machine.transitions import (
    TERMINAL_STATUSES,
    TransitionRule,
    get_transition_rule,
)


def validate_terminal_status(application: Application) -> None:
    """Выбрасывает 409 INVALID_TRANSITION, если заявка уже в терминальном статусе."""
    status = ApplicationStatus(application.status)
    if status in TERMINAL_STATUSES:
        raise ApiError(
            status_code=409,
            code=ErrorCode.INVALID_TRANSITION,
            message=f"Заявка находится в финальном статусе '{status.value}', дальнейшие переходы невозможны",
        )


def validate_optimistic_lock(application: Application, expected_version: int | None) -> None:
    """Проверяет соответствие версии заявки переданному expected_version (If-Match)."""
    if expected_version is not None and application.version != expected_version:
        raise ApiError(
            status_code=409,
            code=ErrorCode.VERSION_CONFLICT,
            message=(
                f"Версия заявки изменилась: текущая {application.version}, ожидалась {expected_version}. "
                "Обновите данные заявки и повторите запрос."
            ),
        )


def validate_ownership_and_actor(
    application: Application,
    target_status: ApplicationStatus,
    actor_type: ActorType,
    actor_id: str | uuid.UUID | None,
    actor_role: str | None = None,
    is_escalated: bool = False,
) -> TransitionRule:
    """Проверяет права актора на переход и возвращает правило перехода.

    Правила:
    - Чужая заявка для CLIENT даёт 404 NOT_FOUND (существование не раскрываем).
    - Роль оператора проверяется (OPERATOR или ADMIN), иначе 403 FORBIDDEN.
    - Переход из MANUAL_REVIEW требует, чтобы заявка была взята именно этим оператором (иначе 409 CONFLICT).
    - Недопустимый переход даёт 409 INVALID_TRANSITION.
    """
    from_status = ApplicationStatus(application.status)

    # 1. Проверка владения клиентом
    if actor_type == ActorType.CLIENT:
        if actor_id is None or str(application.created_by) != str(actor_id):
            # Контракт openapi: клиент к чужой заявке получает 404
            raise ApiError(
                status_code=404,
                code=ErrorCode.NOT_FOUND,
                message="Заявка не найдена",
            )
        if actor_role is not None and actor_role != Role.CLIENT.value:
            raise ApiError(
                status_code=403,
                code=ErrorCode.FORBIDDEN,
                message="Операция доступна только клиенту",
            )

    # 2. Проверка роли оператора
    if actor_type == ActorType.OPERATOR:
        if actor_role is not None and actor_role not in (Role.OPERATOR.value, Role.ADMIN.value):
            raise ApiError(
                status_code=403,
                code=ErrorCode.FORBIDDEN,
                message="Недостаточно прав: требуется роль OPERATOR или ADMIN",
            )

    # 3. Проверка существования перехода в графе
    rule = get_transition_rule(from_status, target_status)
    if rule is None:
        raise ApiError(
            status_code=409,
            code=ErrorCode.INVALID_TRANSITION,
            message=f"Недопустимый переход заявки из статуса '{from_status.value}' в '{target_status.value}'",
        )

    # 4. Проверка допустимости актора для данного перехода
    if actor_type not in rule.allowed_actors:
        raise ApiError(
            status_code=409,
            code=ErrorCode.INVALID_TRANSITION,
            message=(
                f"Переход из '{from_status.value}' в '{target_status.value}' недопустим для актора '{actor_type.value}'"
            ),
        )

    # 5. Проверка назначения оператора при переходе из MANUAL_REVIEW
    if from_status == ApplicationStatus.MANUAL_REVIEW and actor_type == ActorType.OPERATOR:
        if application.assigned_operator_id is None:
            raise ApiError(
                status_code=409,
                code=ErrorCode.CONFLICT,
                message="Заявка ещё не взята в работу. Сначала возьмите заявку (take)",
            )
        if str(application.assigned_operator_id) != str(actor_id):
            raise ApiError(
                status_code=409,
                code=ErrorCode.CONFLICT,
                message="Заявка взята в работу другим оператором",
            )

    return rule


def should_escalate_info_rounds(
    application: Application,
    target_status: ApplicationStatus,
    max_info_rounds: int,
) -> bool:
    """Проверяет, не исчерпан ли лимит раундов уточнений при переходе в NEEDS_INFO.

    Если заявка пытается перейти в NEEDS_INFO, но application.info_rounds >= max_info_rounds,
    переход должен быть перенаправлен в MANUAL_REVIEW с причиной INFO_ROUNDS_EXCEEDED.
    """
    if target_status == ApplicationStatus.NEEDS_INFO:
        return application.info_rounds >= max_info_rounds
    return False
