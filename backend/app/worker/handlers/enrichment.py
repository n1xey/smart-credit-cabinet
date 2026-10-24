"""Обработчик шага enrichment кредитного конвейера.

Выполняет:
1. Проверку ранее сохранённых успешных результатов обогащения (BKI, EGRUL).
2. Сетевые запросы к внешним сервисам ДО блокировки заявки и вызова transition().
3. Фиксацию успешных ответов в отдельной транзакции (транзакционная изоляция),
   чтобы при сбое второго сервиса повтор не перезапрашивал первый.
4. При успехе обоих источников -> переход в SCORING (автоматически ставит задачу scoring_decision).
"""
from datetime import datetime, timezone
import logging
import uuid

from sqlalchemy.orm import Session

from app.enums import ActorType, ApplicationStatus
from app.models.tables import Application, Company, EnrichmentResult, Job
from app.state_machine import transition
from app.worker.deps import WorkerDeps
from app.worker.queue import complete_job

log = logging.getLogger("app.worker.handlers.enrichment")


def _save_enrichment_result(
    session_factory,
    application_id: uuid.UUID,
    source: str,
    payload: dict,
    status: str = "OK",
) -> None:
    """Сохраняет результат обогащения в отдельной независимой транзакции."""
    now = datetime.now(timezone.utc)
    with session_factory() as enr_session:
        try:
            entry = (
                enr_session.query(EnrichmentResult)
                .filter(
                    EnrichmentResult.application_id == application_id,
                    EnrichmentResult.source == source,
                )
                .first()
            )
            if entry is None:
                entry = EnrichmentResult(
                    id=uuid.uuid4(),
                    application_id=application_id,
                    source=source,
                    payload=payload,
                    status=status,
                    attempts=1,
                    fetched_at=now,
                )
                enr_session.add(entry)
            else:
                entry.payload = payload
                entry.status = status
                entry.attempts += 1
                entry.fetched_at = now
            enr_session.commit()
        except Exception:
            enr_session.rollback()
            log.exception(
                "failed_to_save_enrichment_result",
                extra={"application_id": str(application_id), "source": source},
            )
            raise


def handle_enrichment(session: Session, job: Job, deps: WorkerDeps) -> None:
    """Обогащает заявку данными из БКИ и ЕГРЮЛ."""
    app = (
        session.query(Application)
        .filter(Application.id == job.application_id)
        .first()
    )
    if app is None:
        log.warning("enrichment_application_not_found", extra={"application_id": str(job.application_id)})
        complete_job(session, job)
        return

    company = session.query(Company).filter(Company.id == app.company_id).first()
    if company is None:
        log.error("enrichment_company_not_found", extra={"company_id": str(app.company_id)})
        complete_job(session, job)
        return

    # 1. Проверяем, какие данные уже сохранены
    existing_bki = (
        session.query(EnrichmentResult)
        .filter(
            EnrichmentResult.application_id == app.id,
            EnrichmentResult.source == "BKI",
            EnrichmentResult.status == "OK",
        )
        .first()
    )
    existing_egrul = (
        session.query(EnrichmentResult)
        .filter(
            EnrichmentResult.application_id == app.id,
            EnrichmentResult.source == "EGRUL",
            EnrichmentResult.status == "OK",
        )
        .first()
    )

    # 2. Сетевые запросы к внешним сервисам (ДО вызова transition)
    if existing_bki is None:
        log.info("fetching_bki_report", extra={"inn": company.inn, "application_id": str(app.id)})
        bki_report = deps.bki_client.get_report(company.inn)
        bki_payload = {
            "inn": bki_report.inn,
            "rating": bki_report.rating,
            "active_credits_count": bki_report.active_credits_count,
            "overdue_amount_rub": bki_report.overdue_amount_rub,
            "raw": bki_report.raw_payload,
        }
        _save_enrichment_result(deps.session_factory, app.id, "BKI", bki_payload, status="OK")

    if existing_egrul is None:
        log.info("fetching_egrul_data", extra={"inn": company.inn, "application_id": str(app.id)})
        egrul_company = deps.egrul_client.lookup(company.inn)
        egrul_payload = egrul_company.model_dump() if egrul_company is not None else {}
        _save_enrichment_result(deps.session_factory, app.id, "EGRUL", egrul_payload, status="OK")

    # 3. Оба сервиса успешно ответили -> переводим заявку в SCORING
    transition(
        session=session,
        application=app,
        to_status=ApplicationStatus.SCORING,
        actor_type=ActorType.SYSTEM,
        comment="Обогащение данными БКИ и ЕГРЮЛ успешно завершено",
    )
    complete_job(session, job)
