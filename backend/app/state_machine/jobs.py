"""Управление постановкой фоновых задач воркера в таблицу jobs."""
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.enums import ApplicationStatus, JobState
from app.models.tables import Application, Job


def enqueue_job(
    session: Session,
    application_id: uuid.UUID,
    job_type: str,
    step_key: str,
    payload: dict | None = None,
    run_after: datetime | None = None,
) -> Job:
    """Ставит фоновую задачу в очередь PostgreSQL (таблица jobs) с учётом идемпотентности.

    Если задача с таким (application_id, type, step_key) уже существует, возвращает её.
    """
    now = datetime.now(timezone.utc)
    target_run_after = run_after or now

    existing = (
        session.query(Job)
        .filter(
            Job.application_id == application_id,
            Job.type == job_type,
            Job.step_key == step_key,
        )
        .first()
    )
    if existing is not None:
        return existing

    job = Job(
        application_id=application_id,
        type=job_type,
        step_key=step_key,
        payload=payload,
        state=JobState.PENDING.value,
        attempts=0,
        run_after=target_run_after,
        created_at=now,
        updated_at=now,
    )
    session.add(job)
    return job


def enqueue_transition_job(
    session: Session,
    application: Application,
    target_status: ApplicationStatus,
) -> Job | None:
    """Автоматически ставит задачу для воркера при переходе в соответствующий статус.

    Цепочка согласно docs/STATE_MACHINE.md:
    - SUBMITTED -> data_check
    - DATA_CHECK (из NEEDS_INFO) -> data_check
    - ENRICHMENT -> enrichment
    - SCORING -> scoring_decision
    - ACCEPTED -> prepare_documents
    """
    step_key = str(application.version)

    match target_status:
        case ApplicationStatus.SUBMITTED:
            return enqueue_job(session, application.id, "data_check", step_key)
        case ApplicationStatus.DATA_CHECK:
            return enqueue_job(session, application.id, "data_check", step_key)
        case ApplicationStatus.ENRICHMENT:
            return enqueue_job(session, application.id, "enrichment", step_key)
        case ApplicationStatus.SCORING:
            return enqueue_job(session, application.id, "scoring_decision", step_key)
        case ApplicationStatus.ACCEPTED:
            return enqueue_job(session, application.id, "prepare_documents", step_key)
        case _:
            return None
