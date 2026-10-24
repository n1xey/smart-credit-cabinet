"""Транзакционная очередь задач кредитного конвейера в PostgreSQL (таблица jobs).

Обеспечивает:
1. Захват задач конкурентными процессами через SELECT ... FOR UPDATE SKIP LOCKED.
2. Экспоненциальный бэкофф при повторах (PENDING с обновлением run_after).
3. Перевод в FAILED и аварийный перевод заявки в MANUAL_REVIEW с кодом PIPELINE_ERROR.
4. Возврат зависших задач (reclaim_stuck_jobs) для watchdog.
"""
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import logging
import uuid

from sqlalchemy.orm import Session

from app.enums import ActorType, ApplicationStatus, JobState
from app.models.tables import Application, Job
from app.state_machine import TERMINAL_STATUSES, transition
from app.state_machine.transitions import get_allowed_targets

log = logging.getLogger("app.worker.queue")


def claim_next_job(session: Session) -> Job | None:
    """Захватывает следующую готовую к выполнению задачу из очереди.

    Выбирает одну задачу в статусе PENDING, у которой наступил срок run_after,
    в порядке возрастания run_after и created_at.
    Использует FOR UPDATE SKIP LOCKED для безопасной работы нескольких воркеров.
    Переводит задачу в RUNNING, увеличивает счётчик attempts и выставляет locked_at.

    ВНИМАНИЕ: Вызывающий код обязан сразу зафиксировать транзакцию (session.commit()),
    чтобы не удерживать блокировку на время длительной обработки задачи.
    """
    now = datetime.now(timezone.utc)
    job = (
        session.query(Job)
        .filter(
            Job.state == JobState.PENDING.value,
            Job.run_after <= now,
        )
        .order_by(Job.run_after.asc(), Job.created_at.asc())
        .with_for_update(skip_locked=True)
        .first()
    )
    if job is None:
        return None

    job.state = JobState.RUNNING.value
    job.locked_at = now
    job.attempts += 1
    job.updated_at = now
    return job


def complete_job(session: Session, job: Job) -> None:
    """Фиксирует успешное завершение задачи (DONE).

    Сбрасывает locked_at и обновляет updated_at.
    Вызывается в рамках рабочей транзакции обработчика шага.
    """
    now = datetime.now(timezone.utc)
    job.state = JobState.DONE.value
    job.locked_at = None
    job.updated_at = now


def reclaim_stuck_jobs(session: Session, lock_timeout_sec: int) -> int:
    """Возвращает в PENDING зависшие задачи, находящиеся в RUNNING дольше lock_timeout_sec.

    Сбрасывает locked_at в None и обновляет updated_at.
    Используется периодическим процессом watchdog.
    Возвращает количество сброшенных задач.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=lock_timeout_sec)
    stuck_jobs = (
        session.query(Job)
        .filter(
            Job.state == JobState.RUNNING.value,
            Job.locked_at < cutoff,
        )
        .with_for_update()
        .all()
    )
    now = datetime.now(timezone.utc)
    for job in stuck_jobs:
        job.state = JobState.PENDING.value
        job.locked_at = None
        job.updated_at = now
        log.warning(
            "reclaimed_stuck_job",
            extra={
                "job_id": str(job.id),
                "application_id": str(job.application_id) if job.application_id else None,
                "type": job.type,
                "step_key": job.step_key,
                "attempts": job.attempts,
            },
        )
    return len(stuck_jobs)


def _handle_emergency_app_failure(session: Session, app_id: uuid.UUID, error_message: str) -> None:
    """Аварийная обработка заявки при исчерпании попыток выполнения задачи (job -> FAILED).

    Переводит заявку в MANUAL_REVIEW с кодом PIPELINE_ERROR с учётом графа переходов:
    1. Терминальный статус (REJECTED, CANCELLED, EXPIRED, DISBURSED) -> переход запрещён, выход.
    2. Статус SUBMITTED (data_check упал на самом старте до внутреннего перехода в DATA_CHECK):
       прямого перехода SUBMITTED -> MANUAL_REVIEW в графе нет, поэтому выполняется 2 шага:
       а) SUBMITTED -> DATA_CHECK (с enqueue_jobs=False, reason_code="PIPELINE_ERROR")
       б) DATA_CHECK -> MANUAL_REVIEW (с enqueue_jobs=False, reason_code="PIPELINE_ERROR")
    3. Любой другой статус, из которого разрешён SYSTEM -> MANUAL_REVIEW
       (DATA_CHECK, ENRICHMENT, SCORING, ACCEPTED): прямой переход в MANUAL_REVIEW.
    4. Если переход не разрешён графом, пишется предупреждение без необработанного исключения.
    """
    app = (
        session.query(Application)
        .filter(Application.id == app_id)
        .with_for_update()
        .first()
    )
    if app is None:
        log.warning("emergency_transition_app_not_found", extra={"application_id": str(app_id)})
        return

    current_status = ApplicationStatus(app.status)
    if current_status in TERMINAL_STATUSES:
        log.info(
            "emergency_transition_skipped_terminal",
            extra={"application_id": str(app_id), "status": current_status.value},
        )
        return

    if current_status == ApplicationStatus.SUBMITTED:
        # data_check упал до перехода SUBMITTED -> DATA_CHECK
        transition(
            session=session,
            application=app,
            to_status=ApplicationStatus.DATA_CHECK,
            actor_type=ActorType.SYSTEM,
            actor_id=None,
            actor_role="SYSTEM",
            reason_code="PIPELINE_ERROR",
            comment="Аварийная фиксация шага проверок",
            enqueue_jobs=False,
        )
        transition(
            session=session,
            application=app,
            to_status=ApplicationStatus.MANUAL_REVIEW,
            actor_type=ActorType.SYSTEM,
            actor_id=None,
            actor_role="SYSTEM",
            reason_code="PIPELINE_ERROR",
            comment=f"Аварийная передача оператору после исчерпания попыток: {error_message[:200]}",
            enqueue_jobs=False,
        )
        return

    allowed = get_allowed_targets(current_status, ActorType.SYSTEM)
    if ApplicationStatus.MANUAL_REVIEW in allowed:
        transition(
            session=session,
            application=app,
            to_status=ApplicationStatus.MANUAL_REVIEW,
            actor_type=ActorType.SYSTEM,
            actor_id=None,
            actor_role="SYSTEM",
            reason_code="PIPELINE_ERROR",
            comment=f"Аварийная передача оператору после исчерпания попыток: {error_message[:200]}",
            enqueue_jobs=False,
        )
    else:
        log.warning(
            "emergency_transition_not_allowed",
            extra={"application_id": str(app_id), "status": current_status.value},
        )


def fail_job(
    session_factory: Callable[[], Session],
    job_id: uuid.UUID,
    app_id: uuid.UUID | None,
    error_message: str,
    max_attempts: int,
    base_backoff_sec: int,
) -> None:
    """Обрабатывает ошибку выполнения задачи в отдельной чистой транзакции.

    Если attempts < max_attempts:
      - Переводит задачу в PENDING;
      - Рассчитывает экспоненциальный бэкофф: delay = base_backoff_sec * (2 ** (attempts - 1));
      - Устанавливает run_after = now + delay.

    Если attempts >= max_attempts:
      - Переводит задачу в FAILED;
      - Выполняет аварийный переход связанной заявки в MANUAL_REVIEW через _handle_emergency_app_failure.
    """
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        try:
            job = (
                session.query(Job)
                .filter(Job.id == job_id)
                .with_for_update()
                .first()
            )
            if job is None:
                log.warning("fail_job_not_found", extra={"job_id": str(job_id)})
                return

            job.locked_at = None
            job.last_error = error_message[:2000]

            if job.attempts < max_attempts:
                delay = base_backoff_sec * (2 ** (job.attempts - 1))
                job.state = JobState.PENDING.value
                job.run_after = now + timedelta(seconds=delay)
                job.updated_at = now
                log.warning(
                    "job_retry_scheduled",
                    extra={
                        "job_id": str(job_id),
                        "application_id": str(app_id) if app_id else None,
                        "attempt": job.attempts,
                        "max_attempts": max_attempts,
                        "delay_sec": delay,
                        "error": error_message[:200],
                    },
                )
            else:
                job.state = JobState.FAILED.value
                job.updated_at = now
                log.error(
                    "job_exhausted_attempts",
                    extra={
                        "job_id": str(job_id),
                        "application_id": str(app_id) if app_id else None,
                        "attempts": job.attempts,
                        "error": error_message[:200],
                    },
                )
                if app_id is not None:
                    _handle_emergency_app_failure(session, app_id, error_message)

            session.commit()
        except Exception:
            session.rollback()
            log.exception(
                "fail_job_transaction_failed",
                extra={"job_id": str(job_id), "application_id": str(app_id) if app_id else None},
            )
            raise
