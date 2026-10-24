"""Комплексные тесты кредитного конвейера, воркера и фоновых задач (Задача 6).

Покрывают все 18 сценариев:
1. test_pipeline_happy_path_offer
2. test_pipeline_happy_path_counter_offer
3. test_pipeline_scoring_manual_review
4. test_pipeline_scoring_rejected
5. test_pipeline_scoring_needs_info
6. test_data_check_invalid_inn_checksum
7. test_data_check_business_age_too_young
8. test_data_check_missing_required_documents
9. test_prepare_documents_to_signing
10. test_data_check_no_duplicate_jobs_per_version
11. test_enrichment_bki_retry_isolated
12. test_enrichment_retry_exhausted_to_manual_review
13. test_watchdog_expires_overdue_applications
14. test_watchdog_does_not_expire_active_or_terminal
15. test_watchdog_unstucks_pipeline_without_active_jobs
16. test_watchdog_reclaims_stuck_running_jobs
17. test_runner_run_once_returns_zero
18. test_runner_unknown_job_type_fails
"""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import uuid

import pytest
from sqlalchemy.orm import Session

from app.api.schemas.company import CompanyInput
from app.config import Settings
from app.enums import ActorType, ApplicationStatus, JobState, LegalForm, OfferState, Role
from app.models.tables import (
    Application,
    ApplicationStatusHistory,
    Company,
    Decision as DBDecision,
    Document,
    EnrichmentResult,
    InfoRequest,
    Job,
    Offer,
    Product,
    ScoringResult as DBScoringResult,
    User,
)
from app.services.bki_port import BkiReport, SourceUnavailableError
from app.services.scoring_port import DecisionOffer, DecisionOutput
from app.state_machine import enqueue_job, transition
from app.worker.deps import WorkerDeps, get_worker_deps
from app.worker.runner import WorkerRunner
from tests.fakes.fake_scoring import (
    FakeBkiClient,
    FakeDecisionService,
    FakeEgrulClient,
    FakeScoringService,
)


def generate_valid_inn() -> str:
    """Генерирует уникальный валидный 10-значный ИНН ЮЛ с корректной контрольной суммой ФНС."""
    from app.services.inn_validator import _W10
    base = [7, 7] + [int(c) for c in f"{uuid.uuid4().int % 10_000_000:07d}"]
    checksum = sum(d * w for d, w in zip(base, _W10)) % 11 % 10
    return "".join(map(str, base)) + str(checksum)


def _create_seed_entities(
    session: Session,
    inn: str | None = None,
    legal_form: str = "OOO",
    reg_date: date | str = date(2020, 1, 15),
    product_code: str | None = None,
    min_business_age_months: int = 6,
    required_documents: list[str] | None = None,
    initial_status: ApplicationStatus = ApplicationStatus.SUBMITTED,
) -> tuple[User, Company, Product, Application]:
    """Вспомогательная функция для генерации тестовых сущностей."""
    suffix = uuid.uuid4().hex[:6]
    user = User(
        id=uuid.uuid4(),
        email=f"client_{suffix}@example.com",
        full_name="Тестовый Предприниматель",
        password_hash="fakehash",
        role=Role.CLIENT.value,
    )
    session.add(user)
    session.flush()

    actual_inn = inn or generate_valid_inn()
    parsed_reg_date = (
        datetime.strptime(reg_date, "%Y-%m-%d").date()
        if isinstance(reg_date, str)
        else reg_date
    )
    company = Company(
        id=uuid.uuid4(),
        owner_id=user.id,
        inn=actual_inn,
        name=f'ООО "Компания {suffix}"',
        legal_form=legal_form,
        registration_date=parsed_reg_date,
        okved="62.01",
        address="г. Москва",
    )
    session.add(company)
    session.flush()

    p_code = product_code or f"PRODUCT_{suffix}"
    product = Product(
        code=p_code,
        name="Тестовый продукт",
        description="Описание",
        min_amount_rub=100_000,
        max_amount_rub=10_000_000,
        min_term_months=3,
        max_term_months=36,
        base_rate_percent=15.0,
        auto_limit_rub=3_000_000,
        min_business_age_months=min_business_age_months,
        required_documents=required_documents or [],
    )
    session.add(product)
    session.flush()

    app = Application(
        id=uuid.uuid4(),
        company_id=company.id,
        created_by=user.id,
        product_code=product.code,
        amount_rub=1_000_000,
        term_months=12,
        purpose="Пополнение оборотных средств",
        revenue_12m_rub=10_000_000,
        net_profit_12m_rub=1_500_000,
        existing_monthly_payments_rub=50_000,
        status=initial_status.value,
        version=1,
    )
    session.add(app)
    session.flush()

    # Если статус SUBMITTED, сразу ставим задачу data_check
    if initial_status == ApplicationStatus.SUBMITTED:
        enqueue_job(session, app.id, "data_check", str(app.version))

    session.commit()
    return user, company, product, app


def _build_test_deps(
    session_factory,
    tmp_path: Path,
    scoring=None,
    decision=None,
    bki=None,
    egrul=None,
    job_max_attempts=3,
    job_base_backoff_sec=1,
) -> WorkerDeps:
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        uploads_dir=uploads_dir,
        job_max_attempts=job_max_attempts,
        job_base_backoff_sec=job_base_backoff_sec,
        job_lock_timeout_sec=120,
        watchdog_interval_sec=60,
    )
    return get_worker_deps(
        session_factory=session_factory,
        scoring_service=scoring or FakeScoringService(),
        decision_service=decision or FakeDecisionService(),
        bki_client=bki or FakeBkiClient(),
        egrul_client=egrul or FakeEgrulClient(),
        uploads_dir=uploads_dir,
        settings=settings,
    )


# ---------------------------------------------------------------------------
# 1. Happy Path: SUBMITTED -> OFFER
# ---------------------------------------------------------------------------
def test_pipeline_happy_path_offer(worker_db, tmp_path):
    engine, session_factory = worker_db
    with session_factory() as session:
        _, _, _, app = _create_seed_entities(session)
        app_id = app.id

    deps = _build_test_deps(session_factory, tmp_path)
    runner = WorkerRunner(deps)

    # Запускаем конвейер
    runner.run_once()

    with session_factory() as session:
        refreshed = session.query(Application).filter_by(id=app_id).first()
        assert refreshed.status == ApplicationStatus.OFFER.value

        # Проверяем оффер
        offer = session.query(Offer).filter_by(application_id=app_id).first()
        assert offer is not None
        assert offer.state == OfferState.ACTIVE.value
        assert offer.kind == "ORIGINAL"
        assert offer.amount_rub == 1_000_000
        assert offer.monthly_payment_rub > 0

        # Проверяем историю переходов
        hist = session.query(ApplicationStatusHistory).filter_by(application_id=app_id).all()
        to_statuses = [h.to_status for h in hist]
        assert to_statuses == [
            ApplicationStatus.DATA_CHECK.value,
            ApplicationStatus.ENRICHMENT.value,
            ApplicationStatus.SCORING.value,
            ApplicationStatus.OFFER.value,
        ]


# ---------------------------------------------------------------------------
# 2. Happy Path: COUNTER_OFFER
# ---------------------------------------------------------------------------
def test_pipeline_happy_path_counter_offer(worker_db, tmp_path):
    engine, session_factory = worker_db
    with session_factory() as session:
        _, _, _, app = _create_seed_entities(session)
        app_id = app.id

    decision = FakeDecisionService(outcome="COUNTER_OFFER")
    deps = _build_test_deps(session_factory, tmp_path, decision=decision)
    runner = WorkerRunner(deps)
    runner.run_once()

    with session_factory() as session:
        refreshed = session.query(Application).filter_by(id=app_id).first()
        assert refreshed.status == ApplicationStatus.COUNTER_OFFER.value

        offer = session.query(Offer).filter_by(application_id=app_id).first()
        assert offer is not None
        assert offer.kind == "COUNTER"
        assert offer.state == OfferState.ACTIVE.value


# ---------------------------------------------------------------------------
# 3. Скоринг -> MANUAL_REVIEW
# ---------------------------------------------------------------------------
def test_pipeline_scoring_manual_review(worker_db, tmp_path):
    engine, session_factory = worker_db
    with session_factory() as session:
        _, _, _, app = _create_seed_entities(session)
        app_id = app.id

    decision = FakeDecisionService(
        outcome="MANUAL_REVIEW",
        reason_codes=["BORDERLINE_SCORE"],
        comment="Пограничный балл",
    )
    deps = _build_test_deps(session_factory, tmp_path, decision=decision)
    runner = WorkerRunner(deps)
    runner.run_once()

    with session_factory() as session:
        refreshed = session.query(Application).filter_by(id=app_id).first()
        assert refreshed.status == ApplicationStatus.MANUAL_REVIEW.value


# ---------------------------------------------------------------------------
# 4. Скоринг -> REJECTED
# ---------------------------------------------------------------------------
def test_pipeline_scoring_rejected(worker_db, tmp_path):
    engine, session_factory = worker_db
    with session_factory() as session:
        _, _, _, app = _create_seed_entities(session)
        app_id = app.id

    decision = FakeDecisionService(
        outcome="REJECTED",
        reason_codes=["LOW_SCORE"],
        comment="Низкий скоринговый балл",
    )
    deps = _build_test_deps(session_factory, tmp_path, decision=decision)
    runner = WorkerRunner(deps)
    runner.run_once()

    with session_factory() as session:
        refreshed = session.query(Application).filter_by(id=app_id).first()
        assert refreshed.status == ApplicationStatus.REJECTED.value


# ---------------------------------------------------------------------------
# 5. Скоринг -> NEEDS_INFO
# ---------------------------------------------------------------------------
def test_pipeline_scoring_needs_info(worker_db, tmp_path):
    engine, session_factory = worker_db
    with session_factory() as session:
        _, _, _, app = _create_seed_entities(session)
        app_id = app.id

    decision = FakeDecisionService(
        outcome="NEEDS_INFO",
        reason_codes=["FINANCIALS_UNCLEAR"],
        comment="Нужны пояснения по выручке",
        info_request_items=["Пояснительная записка к балансу"],
    )
    deps = _build_test_deps(session_factory, tmp_path, decision=decision)
    runner = WorkerRunner(deps)
    runner.run_once()

    with session_factory() as session:
        refreshed = session.query(Application).filter_by(id=app_id).first()
        assert refreshed.status == ApplicationStatus.NEEDS_INFO.value

        info_req = session.query(InfoRequest).filter_by(application_id=app_id).first()
        assert info_req is not None
        assert info_req.items == ["Пояснительная записка к балансу"]


# ---------------------------------------------------------------------------
# 6. Стоп-фактор: Невалидная контрольная сумма ИНН
# ---------------------------------------------------------------------------
def test_data_check_invalid_inn_checksum(worker_db, tmp_path):
    engine, session_factory = worker_db
    with session_factory() as session:
        # Невалидный ИНН 10 цифр с ошибочной контрольной суммой
        _, _, _, app = _create_seed_entities(session, inn="7707083890")
        app_id = app.id

    deps = _build_test_deps(session_factory, tmp_path)
    runner = WorkerRunner(deps)
    runner.run_once()

    with session_factory() as session:
        refreshed = session.query(Application).filter_by(id=app_id).first()
        assert refreshed.status == ApplicationStatus.REJECTED.value

        hist = session.query(ApplicationStatusHistory).filter_by(application_id=app_id).all()
        assert hist[-1].reason_code == "INVALID_INN"


# ---------------------------------------------------------------------------
# 7. Стоп-фактор: Недостаточный возраст бизнеса
# ---------------------------------------------------------------------------
def test_data_check_business_age_too_young(worker_db, tmp_path):
    engine, session_factory = worker_db
    reg_date = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    with session_factory() as session:
        _, _, _, app = _create_seed_entities(
            session,
            inn="7707083893",
            reg_date=reg_date,
            min_business_age_months=12,
        )
        app_id = app.id

    deps = _build_test_deps(session_factory, tmp_path)
    runner = WorkerRunner(deps)
    runner.run_once()

    with session_factory() as session:
        refreshed = session.query(Application).filter_by(id=app_id).first()
        assert refreshed.status == ApplicationStatus.REJECTED.value

        hist = session.query(ApplicationStatusHistory).filter_by(application_id=app_id).all()
        assert hist[-1].reason_code == "PRODUCT_NOT_AVAILABLE"


# ---------------------------------------------------------------------------
# 8. Стоп-фактор: Отсутствуют обязательные документы
# ---------------------------------------------------------------------------
def test_data_check_missing_required_documents(worker_db, tmp_path):
    engine, session_factory = worker_db
    with session_factory() as session:
        _, _, _, app = _create_seed_entities(
            session,
            inn="7707083893",
            required_documents=["FINANCIAL_STATEMENT"],
        )
        app_id = app.id

    deps = _build_test_deps(session_factory, tmp_path)
    runner = WorkerRunner(deps)
    runner.run_once()

    with session_factory() as session:
        refreshed = session.query(Application).filter_by(id=app_id).first()
        assert refreshed.status == ApplicationStatus.NEEDS_INFO.value

        info_req = session.query(InfoRequest).filter_by(application_id=app_id).first()
        assert info_req is not None
        assert info_req.items == ["FINANCIAL_STATEMENT"]


# ---------------------------------------------------------------------------
# 9. Подготовка документов: ACCEPTED -> SIGNING
# ---------------------------------------------------------------------------
def test_prepare_documents_to_signing(worker_db, tmp_path):
    engine, session_factory = worker_db
    with session_factory() as session:
        _, _, _, app = _create_seed_entities(session, initial_status=ApplicationStatus.ACCEPTED)
        app_id = app.id

        # Создаём принятый оффер
        offer = Offer(
            id=uuid.uuid4(),
            application_id=app.id,
            kind="ORIGINAL",
            amount_rub=1_000_000,
            term_months=12,
            rate_percent=15.0,
            monthly_payment_rub=95_000,
            valid_until=datetime.now(timezone.utc) + timedelta(days=3),
            state=OfferState.ACCEPTED.value,
        )
        session.add(offer)

        # Ставим задачу prepare_documents
        enqueue_job(session, app.id, "prepare_documents", str(app.version))
        session.commit()

    deps = _build_test_deps(session_factory, tmp_path)
    runner = WorkerRunner(deps)
    runner.run_once()

    with session_factory() as session:
        refreshed = session.query(Application).filter_by(id=app_id).first()
        assert refreshed.status == ApplicationStatus.SIGNING.value

        # Проверяем сохранённый файл документа
        doc = session.query(Document).filter_by(application_id=app_id).first()
        assert doc is not None
        assert doc.filename == "credit_agreement.txt"
        assert Path(doc.storage_path).exists()
        content = Path(doc.storage_path).read_text(encoding="utf-8")
        assert "КРЕДИТНЫЙ ДОГОВОР" in content
        assert "1,000,000" in content


# ---------------------------------------------------------------------------
# 10. Дубль задачи data_check: ровно одна задача на версию
# ---------------------------------------------------------------------------
def test_data_check_no_duplicate_jobs_per_version(worker_db, tmp_path):
    """После полного прогона от SUBMITTED до SCORING/OFFER в jobs ровно одна задача data_check на версию."""
    engine, session_factory = worker_db
    with session_factory() as session:
        _, _, _, app = _create_seed_entities(session)
        app_id = app.id

    deps = _build_test_deps(session_factory, tmp_path)
    runner = WorkerRunner(deps)
    runner.run_once()

    with session_factory() as session:
        data_check_jobs = (
            session.query(Job)
            .filter_by(application_id=app_id, type="data_check")
            .all()
        )
        assert len(data_check_jobs) == 1
        assert data_check_jobs[0].state == JobState.DONE.value


# ---------------------------------------------------------------------------
# 11. Транзакционная изоляция обогащения: повтор без повторного вызова БКИ
# ---------------------------------------------------------------------------
def test_enrichment_bki_retry_isolated(worker_db, tmp_path):
    engine, session_factory = worker_db
    with session_factory() as session:
        _, _, _, app = _create_seed_entities(session)
        app_id = app.id

    bki = FakeBkiClient()
    # EGRUL сначала падает, затем поднимается
    egrul = FakeEgrulClient(raise_unreachable=True)

    deps = _build_test_deps(session_factory, tmp_path, bki=bki, egrul=egrul)
    runner = WorkerRunner(deps)

    # Первый запуск: data_check проходит -> enrichment падает на EGRUL
    runner.process_next_job()  # data_check
    runner.process_next_job()  # enrichment (падает)

    assert len(bki.calls) == 1

    # Проверяем, что результат БКИ зафиксирован в DB
    with session_factory() as session:
        bki_res = (
            session.query(EnrichmentResult)
            .filter_by(application_id=app_id, source="BKI", status="OK")
            .first()
        )
        assert bki_res is not None

        # Сбрасываем run_after у задачи enrichment для мгновенного перезапуска
        enr_job = session.query(Job).filter_by(application_id=app_id, type="enrichment").first()
        enr_job.run_after = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()

    # Чиним EGRUL и повторяем
    egrul.raise_unreachable = False
    runner.process_next_job()  # enrichment повтор

    # БКИ НЕ должен был вызываться второй раз!
    assert len(bki.calls) == 1


# ---------------------------------------------------------------------------
# 12. Исчерпание попыток в enrichment -> MANUAL_REVIEW
# ---------------------------------------------------------------------------
def test_enrichment_retry_exhausted_to_manual_review(worker_db, tmp_path):
    engine, session_factory = worker_db
    with session_factory() as session:
        _, _, _, app = _create_seed_entities(session)
        app_id = app.id

    bki = FakeBkiClient(raise_unreachable=True)
    deps = _build_test_deps(session_factory, tmp_path, bki=bki, job_max_attempts=2)
    runner = WorkerRunner(deps)

    runner.process_next_job()  # data_check -> ENRICHMENT

    # Попытка 1
    runner.process_next_job()
    with session_factory() as session:
        job = session.query(Job).filter_by(application_id=app_id, type="enrichment").first()
        assert job.state == JobState.PENDING.value
        assert job.attempts == 1
        job.run_after = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()

    # Попытка 2 (последняя)
    runner.process_next_job()
    with session_factory() as session:
        job = session.query(Job).filter_by(application_id=app_id, type="enrichment").first()
        assert job.state == JobState.FAILED.value
        assert job.attempts == 2

        app = session.query(Application).filter_by(id=app_id).first()
        assert app.status == ApplicationStatus.MANUAL_REVIEW.value


# ---------------------------------------------------------------------------
# 13. Watchdog: перевод просроченных заявок в EXPIRED
# ---------------------------------------------------------------------------
def test_watchdog_expires_overdue_applications(worker_db, tmp_path):
    engine, session_factory = worker_db
    now = datetime.now(timezone.utc)
    expired_ids = []

    with session_factory() as session:
        for status in (
            ApplicationStatus.NEEDS_INFO,
            ApplicationStatus.OFFER,
            ApplicationStatus.COUNTER_OFFER,
            ApplicationStatus.SIGNING,
        ):
            _, _, _, app = _create_seed_entities(session, initial_status=status)
            app.expires_at = now - timedelta(hours=1)
            expired_ids.append(app.id)
        session.commit()

    deps = _build_test_deps(session_factory, tmp_path)
    runner = WorkerRunner(deps)
    runner.run_once()

    with session_factory() as session:
        for app_id in expired_ids:
            app = session.query(Application).filter_by(id=app_id).first()
            assert app.status == ApplicationStatus.EXPIRED.value


# ---------------------------------------------------------------------------
# 14. Watchdog: не трогает активные и уже завершённые заявки
# ---------------------------------------------------------------------------
def test_watchdog_does_not_expire_active_or_terminal(worker_db, tmp_path):
    engine, session_factory = worker_db
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        _, _, _, app_active = _create_seed_entities(session, initial_status=ApplicationStatus.SUBMITTED)
        app_active.expires_at = None

        _, _, _, app_disbursed = _create_seed_entities(session, initial_status=ApplicationStatus.DISBURSED)
        app_disbursed.expires_at = now - timedelta(hours=5)

        session.commit()
        active_id = app_active.id
        disbursed_id = app_disbursed.id

    deps = _build_test_deps(session_factory, tmp_path)
    runner = WorkerRunner(deps)
    runner.run_once()

    with session_factory() as session:
        a1 = session.query(Application).filter_by(id=active_id).first()
        assert a1.status in (ApplicationStatus.OFFER.value, ApplicationStatus.SUBMITTED.value)

        a2 = session.query(Application).filter_by(id=disbursed_id).first()
        assert a2.status == ApplicationStatus.DISBURSED.value


# ---------------------------------------------------------------------------
# 15. Watchdog: восстанавливает зависшие заявки без активных задач
# ---------------------------------------------------------------------------
def test_watchdog_unstucks_pipeline_without_active_jobs(worker_db, tmp_path):
    engine, session_factory = worker_db
    with session_factory() as session:
        # Заявка в SCORING, но в jobs нет ни PENDING, ни RUNNING задач
        _, _, _, app = _create_seed_entities(session, initial_status=ApplicationStatus.SCORING)
        app_id = app.id

    deps = _build_test_deps(session_factory, tmp_path)
    runner = WorkerRunner(deps)

    # Watchdog находит зависшую заявку и создаёт scoring_decision
    runner.run_once()

    with session_factory() as session:
        refreshed = session.query(Application).filter_by(id=app_id).first()
        # После run_once задача была пересоздана и выполнена до статуса OFFER
        assert refreshed.status == ApplicationStatus.OFFER.value


# ---------------------------------------------------------------------------
# 16. Watchdog: возврат зависших RUNNING задач
# ---------------------------------------------------------------------------
def test_watchdog_reclaims_stuck_running_jobs(worker_db, tmp_path):
    engine, session_factory = worker_db
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        _, _, _, app = _create_seed_entities(session, initial_status=ApplicationStatus.ACCEPTED)
        job = Job(
            id=uuid.uuid4(),
            application_id=app.id,
            type="prepare_documents",
            step_key="1",
            state=JobState.RUNNING.value,
            attempts=1,
            locked_at=now - timedelta(seconds=200),
        )
        session.add(job)
        session.commit()
        job_id = job.id

    deps = _build_test_deps(session_factory, tmp_path)
    runner = WorkerRunner(deps)
    runner.run_once()

    with session_factory() as session:
        refreshed_job = session.query(Job).filter_by(id=job_id).first()
        # Watchdog вернул задачу в PENDING, а затем runner выполнил её (DONE)
        assert refreshed_job.state == JobState.DONE.value


# ---------------------------------------------------------------------------
# 17. Runner: run_once возвращает 0
# ---------------------------------------------------------------------------
def test_runner_run_once_returns_zero(worker_db, tmp_path):
    engine, session_factory = worker_db
    deps = _build_test_deps(session_factory, tmp_path)
    runner = WorkerRunner(deps)
    result = runner.run_once()
    assert result == 0


# ---------------------------------------------------------------------------
# 18. Runner: обработка неизвестного типа задачи
# ---------------------------------------------------------------------------
def test_runner_unknown_job_type_fails(worker_db, tmp_path):
    engine, session_factory = worker_db
    with session_factory() as session:
        _, _, _, app = _create_seed_entities(session, initial_status=ApplicationStatus.ACCEPTED)
        job = Job(
            id=uuid.uuid4(),
            application_id=app.id,
            type="unknown_alien_step",
            step_key="1",
            state=JobState.PENDING.value,
            attempts=0,
            run_after=datetime.now(timezone.utc),
        )
        session.add(job)
        session.commit()
        job_id = job.id

    deps = _build_test_deps(session_factory, tmp_path)
    runner = WorkerRunner(deps)
    runner.process_next_job()

    with session_factory() as session:
        refreshed = session.query(Job).filter_by(id=job_id).first()
        assert refreshed.state == JobState.FAILED.value
        assert "Неизвестный тип задачи" in (refreshed.last_error or "")
