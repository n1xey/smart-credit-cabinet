"""Периодические проверки фонового процесса (Watchdog).

Выполняет:
1. reclaim_stuck_jobs: возврат в PENDING зависших задач в статусе RUNNING с locked_at старше lock_timeout_sec.
2. check_expired_applications: перевод просроченных заявок (expires_at <= now) в EXPIRED.
3. check_stuck_applications: восстановление цепочки обработки для заявок в промежуточных статусах
   (SUBMITTED, DATA_CHECK, ENRICHMENT, SCORING, ACCEPTED) без активных задач (PENDING/RUNNING).
"""
from collections.abc import Callable
from datetime import datetime, timezone
import logging
import uuid

from sqlalchemy.orm import Session

from app.enums import ActorType, ApplicationStatus, JobState
from app.models.tables import Application, Job
from app.state_machine import TERMINAL_STATUSES, transition
from app.state_machine.jobs import enqueue_transition_job
from app.worker.deps import WorkerDeps
from app.worker.queue import reclaim_stuck_jobs

log = logging.getLogger("app.worker.watchdog")

ACTIVE_PIPELINE_STATUSES: frozenset[ApplicationStatus] = frozenset(
    {
        ApplicationStatus.SUBMITTED,
        ApplicationStatus.DATA_CHECK,
        ApplicationStatus.ENRICHMENT,
        ApplicationStatus.SCORING,
        ApplicationStatus.ACCEPTED,
    }
)


def check_expired_applications(session_factory: Callable[[], Session]) -> int:
    """Находит все заявки с истёкшим expires_at и переводит их в EXPIRED.

    Обрабатывает каждую заявку в отдельной транзакции для изоляции сбоев.
    """
    now = datetime.now(timezone.utc)
    expired_ids: list[uuid.UUID] = []

    with session_factory() as session:
        candidates = (
            session.query(Application.id)
            .filter(
                Application.expires_at.isnot(None),
                Application.expires_at <= now,
                ~Application.status.in_([s.value for s in TERMINAL_STATUSES]),
            )
            .all()
        )
        expired_ids = [c[0] for c in candidates]

    count = 0
    for app_id in expired_ids:
        with session_factory() as session:
            try:
                app = (
                    session.query(Application)
                    .filter(Application.id == app_id)
                    .with_for_update()
                    .first()
                )
                if app is None:
                    continue

                if ApplicationStatus(app.status) in TERMINAL_STATUSES:
                    continue

                transition(
                    session=session,
                    application=app,
                    to_status=ApplicationStatus.EXPIRED,
                    actor_type=ActorType.SYSTEM,
                    comment="Срок действия истёк (watchdog)",
                )
                session.commit()
                count += 1
                log.info(
                    "application_expired_by_watchdog",
                    extra={"application_id": str(app_id), "previous_status": app.status},
                )
            except Exception:
                session.rollback()
                log.exception(
                    "failed_to_expire_application",
                    extra={"application_id": str(app_id)},
                )

    return count


def check_stuck_applications(session_factory: Callable[[], Session]) -> int:
    """Находит заявки в промежуточных статусах конвейера без активных задач (PENDING/RUNNING)

    и восстанавливает для них задачу в очереди jobs.
    """
    now = datetime.now(timezone.utc)
    stuck_candidates: list[tuple[uuid.UUID, ApplicationStatus]] = []

    with session_factory() as session:
        apps = (
            session.query(Application)
            .filter(Application.status.in_([s.value for s in ACTIVE_PIPELINE_STATUSES]))
            .all()
        )
        for a in apps:
            has_active_job = (
                session.query(Job.id)
                .filter(
                    Job.application_id == a.id,
                    Job.state.in_([JobState.PENDING.value, JobState.RUNNING.value]),
                )
                .first()
                is not None
            )
            if not has_active_job:
                stuck_candidates.append((a.id, ApplicationStatus(a.status)))

    recreated_count = 0
    for app_id, status in stuck_candidates:
        with session_factory() as session:
            try:
                app = (
                    session.query(Application)
                    .filter(Application.id == app_id)
                    .with_for_update()
                    .first()
                )
                if app is None or ApplicationStatus(app.status) != status:
                    continue

                # Проверяем, существует ли FAILED задача с таким step_key
                step_key = str(app.version)
                job = (
                    session.query(Job)
                    .filter(
                        Job.application_id == app.id,
                        Job.step_key == step_key,
                    )
                    .first()
                )
                if job is not None and job.state == JobState.FAILED.value:
                    # Сбрасываем FAILED задачу в PENDING
                    job.state = JobState.PENDING.value
                    job.attempts = 0
                    job.locked_at = None
                    job.run_after = now
                    job.updated_at = now
                else:
                    # Ставим задачу заново
                    enqueue_transition_job(session, app, status)

                session.commit()
                recreated_count += 1
                log.warning(
                    "recreated_stuck_pipeline_job",
                    extra={"application_id": str(app_id), "status": status.value},
                )
            except Exception:
                session.rollback()
                log.exception(
                    "failed_to_recreate_stuck_job",
                    extra={"application_id": str(app_id), "status": status.value},
                )

    return recreated_count


def run_watchdog_cycle(deps: WorkerDeps) -> dict[str, int]:
    """Выполняет один полный цикл watchdog-проверок."""
    # 1. Возврат зависших задач в PENDING
    with deps.session_factory() as session:
        reclaimed = reclaim_stuck_jobs(session, deps.settings.job_lock_timeout_sec)
        session.commit()

    # 2. Проверка просроченных дедлайнов заявок
    expired = check_expired_applications(deps.session_factory)

    # 3. Восстановление зависших промежуточных заявок
    unstuck = check_stuck_applications(deps.session_factory)

    return {
        "reclaimed_jobs": reclaimed,
        "expired_applications": expired,
        "unstuck_applications": unstuck,
    }
