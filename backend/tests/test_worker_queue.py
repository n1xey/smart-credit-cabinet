"""Тесты транзакционной очереди задач (backend/app/worker/queue.py).

Проверяют:
1. Захват задач claim_next_job (PENDING, run_after <= now, инкремент attempts, locked_at).
2. Завершение complete_job (DONE, сброс locked_at).
3. Повтор fail_job с экспоненциальным бэкоффом (attempts < max_attempts).
4. Исчерпание попыток fail_job (attempts >= max_attempts -> FAILED).
5. Аварийный переход SUBMITTED -> DATA_CHECK -> MANUAL_REVIEW при сбое data_check.
6. Аварийный переход DATA_CHECK -> MANUAL_REVIEW при сбое других шагов.
7. Пропуск аварийного перехода для терминальных статусов (CANCELLED).
8. Возврат зависших задач reclaim_stuck_jobs.
"""
from datetime import datetime, timedelta, timezone
import uuid

import pytest
from sqlalchemy.orm import Session

from app.enums import ActorType, ApplicationStatus, JobState, Role
from app.models.tables import Application, ApplicationStatusHistory, Company, Job, Product, User
from app.worker.queue import (
    claim_next_job,
    complete_job,
    fail_job,
    reclaim_stuck_jobs,
)


def _setup_test_data(session: Session) -> tuple[User, Company, Product, Application]:
    """Создаёт тестовых пользователей, компанию, продукт и заявку."""
    user = User(
        id=uuid.uuid4(),
        email=f"client_{uuid.uuid4().hex[:6]}@example.com",
        full_name="Тестовый Клиент",
        password_hash="fakehash",
        role=Role.CLIENT.value,
    )
    session.add(user)
    session.flush()

    company = Company(
        id=uuid.uuid4(),
        owner_id=user.id,
        inn="7707083893",
        name='ООО "Тест"',
        legal_form="OOO",
    )
    session.add(company)
    session.flush()

    product = Product(
        code=f"WORKING_CAPITAL_{uuid.uuid4().hex[:6]}",
        name="Оборотный",
        description="Кредит",
        min_amount_rub=100_000,
        max_amount_rub=5_000_000,
        min_term_months=3,
        max_term_months=12,
        base_rate_percent=15.0,
        auto_limit_rub=1_000_000,
        min_business_age_months=6,
        required_documents=[],
    )
    session.add(product)
    session.flush()

    app = Application(
        id=uuid.uuid4(),
        company_id=company.id,
        created_by=user.id,
        product_code=product.code,
        amount_rub=500_000,
        term_months=12,
        status=ApplicationStatus.SUBMITTED.value,
        version=1,
    )
    session.add(app)
    session.commit()
    return user, company, product, app


def test_claim_next_job_success(worker_db):
    engine, session_factory = worker_db
    with session_factory() as session:
        _, _, _, app = _setup_test_data(session)
        now = datetime.now(timezone.utc)
        job = Job(
            id=uuid.uuid4(),
            application_id=app.id,
            type="data_check",
            step_key="1",
            state=JobState.PENDING.value,
            attempts=0,
            run_after=now - timedelta(seconds=10),
        )
        session.add(job)
        session.commit()

        # Claim
        claimed = claim_next_job(session)
        assert claimed is not None
        assert claimed.id == job.id
        assert claimed.state == JobState.RUNNING.value
        assert claimed.attempts == 1
        assert claimed.locked_at is not None
        session.commit()

        # Повторный claim ничего не находит (задача уже RUNNING)
        assert claim_next_job(session) is None


def test_claim_ignores_future_jobs(worker_db):
    engine, session_factory = worker_db
    with session_factory() as session:
        _, _, _, app = _setup_test_data(session)
        now = datetime.now(timezone.utc)
        job = Job(
            id=uuid.uuid4(),
            application_id=app.id,
            type="data_check",
            step_key="1",
            state=JobState.PENDING.value,
            attempts=0,
            run_after=now + timedelta(seconds=60),
        )
        session.add(job)
        session.commit()

        claimed = claim_next_job(session)
        assert claimed is None


def test_complete_job(worker_db):
    engine, session_factory = worker_db
    with session_factory() as session:
        _, _, _, app = _setup_test_data(session)
        job = Job(
            id=uuid.uuid4(),
            application_id=app.id,
            type="data_check",
            step_key="1",
            state=JobState.RUNNING.value,
            attempts=1,
            locked_at=datetime.now(timezone.utc),
        )
        session.add(job)
        session.commit()

        complete_job(session, job)
        session.commit()

        refreshed = session.query(Job).filter(Job.id == job.id).first()
        assert refreshed.state == JobState.DONE.value
        assert refreshed.locked_at is None


def test_fail_job_retry_backoff(worker_db):
    engine, session_factory = worker_db
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        _, _, _, app = _setup_test_data(session)
        job = Job(
            id=uuid.uuid4(),
            application_id=app.id,
            type="data_check",
            step_key="1",
            state=JobState.RUNNING.value,
            attempts=1,
            locked_at=now,
        )
        session.add(job)
        session.commit()
        job_id = job.id
        app_id = app.id

    # fail_job attempt 1 of 3 (base_backoff=2 -> delay = 2 * (2**0) = 2s)
    fail_job(
        session_factory=session_factory,
        job_id=job_id,
        app_id=app_id,
        error_message="Network timeout",
        max_attempts=3,
        base_backoff_sec=2,
    )

    with session_factory() as session:
        refreshed = session.query(Job).filter(Job.id == job_id).first()
        assert refreshed.state == JobState.PENDING.value
        assert refreshed.locked_at is None
        assert refreshed.last_error == "Network timeout"
        run_after = refreshed.run_after
        if run_after.tzinfo is None:
            run_after = run_after.replace(tzinfo=timezone.utc)
        assert run_after > now


def test_fail_job_exhausted_emergency_transition_submitted(worker_db):
    """При падении в статусе SUBMITTED на последней попытке заявка эскалируется в MANUAL_REVIEW через DATA_CHECK."""
    engine, session_factory = worker_db
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        _, _, _, app = _setup_test_data(session)
        assert app.status == ApplicationStatus.SUBMITTED.value
        job = Job(
            id=uuid.uuid4(),
            application_id=app.id,
            type="data_check",
            step_key="1",
            state=JobState.RUNNING.value,
            attempts=3,
            locked_at=now,
        )
        session.add(job)
        session.commit()
        job_id = job.id
        app_id = app.id

    fail_job(
        session_factory=session_factory,
        job_id=job_id,
        app_id=app_id,
        error_message="Stop factor service unreachable",
        max_attempts=3,
        base_backoff_sec=2,
    )

    with session_factory() as session:
        refreshed_job = session.query(Job).filter(Job.id == job_id).first()
        assert refreshed_job.state == JobState.FAILED.value

        refreshed_app = session.query(Application).filter(Application.id == app_id).first()
        assert refreshed_app.status == ApplicationStatus.MANUAL_REVIEW.value

        # Проверяем историю переходов
        hist = (
            session.query(ApplicationStatusHistory)
            .filter_by(application_id=app_id)
            .order_by(ApplicationStatusHistory.created_at.asc())
            .all()
        )
        # Должны быть SUBMITTED -> DATA_CHECK и DATA_CHECK -> MANUAL_REVIEW
        to_statuses = [h.to_status for h in hist]
        assert ApplicationStatus.DATA_CHECK.value in to_statuses
        assert ApplicationStatus.MANUAL_REVIEW.value in to_statuses
        latest = hist[-1]
        assert latest.reason_code == "PIPELINE_ERROR"


def test_fail_job_exhausted_emergency_transition_data_check(worker_db):
    """При падении в статусе DATA_CHECK на последней попытке заявка напрямую переводится в MANUAL_REVIEW."""
    engine, session_factory = worker_db
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        _, _, _, app = _setup_test_data(session)
        app.status = ApplicationStatus.DATA_CHECK.value
        job = Job(
            id=uuid.uuid4(),
            application_id=app.id,
            type="data_check",
            step_key="1",
            state=JobState.RUNNING.value,
            attempts=3,
            locked_at=now,
        )
        session.add(job)
        session.commit()
        job_id = job.id
        app_id = app.id

    fail_job(
        session_factory=session_factory,
        job_id=job_id,
        app_id=app_id,
        error_message="Check crash",
        max_attempts=3,
        base_backoff_sec=2,
    )

    with session_factory() as session:
        refreshed_job = session.query(Job).filter(Job.id == job_id).first()
        assert refreshed_job.state == JobState.FAILED.value

        refreshed_app = session.query(Application).filter(Application.id == app_id).first()
        assert refreshed_app.status == ApplicationStatus.MANUAL_REVIEW.value


def test_fail_job_exhausted_skipped_on_terminal_status(worker_db):
    """Если заявка уже отменена клиентом (CANCELLED), аварийный переход не выполняется."""
    engine, session_factory = worker_db
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        _, _, _, app = _setup_test_data(session)
        app.status = ApplicationStatus.CANCELLED.value
        job = Job(
            id=uuid.uuid4(),
            application_id=app.id,
            type="data_check",
            step_key="1",
            state=JobState.RUNNING.value,
            attempts=3,
            locked_at=now,
        )
        session.add(job)
        session.commit()
        job_id = job.id
        app_id = app.id

    fail_job(
        session_factory=session_factory,
        job_id=job_id,
        app_id=app_id,
        error_message="Check crash",
        max_attempts=3,
        base_backoff_sec=2,
    )

    with session_factory() as session:
        refreshed_job = session.query(Job).filter(Job.id == job_id).first()
        assert refreshed_job.state == JobState.FAILED.value

        refreshed_app = session.query(Application).filter(Application.id == app_id).first()
        assert refreshed_app.status == ApplicationStatus.CANCELLED.value


def test_reclaim_stuck_jobs(worker_db):
    engine, session_factory = worker_db
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        _, _, _, app = _setup_test_data(session)
        stuck_job = Job(
            id=uuid.uuid4(),
            application_id=app.id,
            type="enrichment",
            step_key="1",
            state=JobState.RUNNING.value,
            attempts=1,
            locked_at=now - timedelta(seconds=200),
        )
        fresh_job = Job(
            id=uuid.uuid4(),
            application_id=app.id,
            type="scoring_decision",
            step_key="1",
            state=JobState.RUNNING.value,
            attempts=1,
            locked_at=now - timedelta(seconds=10),
        )
        session.add_all([stuck_job, fresh_job])
        session.commit()

        # Reclaim with 120s timeout
        reclaimed_count = reclaim_stuck_jobs(session, lock_timeout_sec=120)
        assert reclaimed_count == 1
        session.commit()

        j1 = session.query(Job).filter(Job.id == stuck_job.id).first()
        j2 = session.query(Job).filter(Job.id == fresh_job.id).first()

        assert j1.state == JobState.PENDING.value
        assert j1.locked_at is None

        assert j2.state == JobState.RUNNING.value
        assert j2.locked_at is not None
