"""Обработчик шага scoring_decision кредитного конвейера.

Выполняет:
1. Загрузку данных заявки, компании и результатов обогащения (BKI, EGRUL).
2. Вызов сервиса скоринга (ScoringProtocol) -> сохранение ScoringResult.
3. Вызов сервиса принятия решений (DecisionProtocol) -> сохранение Decision.
4. Ветвление по результату решения:
   - OFFER / COUNTER_OFFER -> сохранение Offer (ACTIVE), переход в OFFER / COUNTER_OFFER.
   - NEEDS_INFO -> создание InfoRequest, переход в NEEDS_INFO.
   - MANUAL_REVIEW -> переход в MANUAL_REVIEW.
   - REJECTED -> переход в REJECTED.
5. Безопасное извлечение reason_code (reason_codes[0] if reason_codes else None).
"""
import logging
import uuid

from sqlalchemy.orm import Session

from app.enums import ActorType, ApplicationStatus, OfferState
from app.models.tables import (
    Application,
    Company,
    Decision as DBDecision,
    EnrichmentResult,
    InfoRequest,
    Job,
    Offer,
    ScoringResult as DBScoringResult,
)
from app.services.scoring_port import ScoringInputs
from app.state_machine import transition
from app.worker.deps import WorkerDeps
from app.worker.queue import complete_job

log = logging.getLogger("app.worker.handlers.scoring")


def handle_scoring_decision(session: Session, job: Job, deps: WorkerDeps) -> None:
    """Выполняет скоринг и применение кредитного решения к заявке."""
    app = (
        session.query(Application)
        .filter(Application.id == job.application_id)
        .with_for_update()
        .first()
    )
    if app is None:
        log.warning("scoring_application_not_found", extra={"application_id": str(job.application_id)})
        complete_job(session, job)
        return

    company = session.query(Company).filter(Company.id == app.company_id).first()
    if company is None:
        log.error("scoring_company_not_found", extra={"company_id": str(app.company_id)})
        complete_job(session, job)
        return

    # 1. Загружаем результаты обогащения
    bki_res = (
        session.query(EnrichmentResult)
        .filter(
            EnrichmentResult.application_id == app.id,
            EnrichmentResult.source == "BKI",
            EnrichmentResult.status == "OK",
        )
        .first()
    )
    egrul_res = (
        session.query(EnrichmentResult)
        .filter(
            EnrichmentResult.application_id == app.id,
            EnrichmentResult.source == "EGRUL",
            EnrichmentResult.status == "OK",
        )
        .first()
    )

    inputs = ScoringInputs(
        application_id=str(app.id),
        inn=company.inn,
        revenue_12m_rub=app.revenue_12m_rub,
        net_profit_12m_rub=app.net_profit_12m_rub,
        existing_monthly_payments_rub=app.existing_monthly_payments_rub,
        requested_amount_rub=app.amount_rub,
        requested_term_months=app.term_months,
        product_code=app.product_code,
        company_name=company.name,
        legal_form=company.legal_form,
        bki_report=bki_res.payload if bki_res else None,
        egrul_data=egrul_res.payload if egrul_res else None,
    )

    # 2. Расчёт скоринга
    scoring_result = deps.scoring_service.calculate_score(inputs)
    factors_data = [
        {"factor": f.factor, "impact": f.impact, "weight": f.weight, "value": f.value}
        for f in scoring_result.factors
    ]
    db_scoring = DBScoringResult(
        id=uuid.uuid4(),
        application_id=app.id,
        score=scoring_result.score,
        grade=scoring_result.grade,
        factors=factors_data,
        knockouts=scoring_result.knockouts,
        model_version=scoring_result.model_version,
    )
    session.add(db_scoring)

    # 3. Принятие решения
    decision = deps.decision_service.make_decision(inputs, scoring_result)
    decided_by = "SYSTEM" if decision.decided_by in ("AUTO", "SYSTEM") else "OPERATOR"
    db_decision = DBDecision(
        id=uuid.uuid4(),
        application_id=app.id,
        outcome=decision.outcome,
        decided_by=decided_by,
        decided_by_id=decision.decided_by_id,
        reason_codes=decision.reason_codes,
        comment=decision.comment,
    )
    session.add(db_decision)

    # Безопасное извлечение reason_code (предотвращает IndexError на пустом списке для офферов)
    reason_code = decision.reason_codes[0] if decision.reason_codes else None

    # 4. Ветвление по исходу
    if decision.outcome in ("OFFER", "COUNTER_OFFER"):
        if decision.offer is None:
            raise ValueError(f"Решение {decision.outcome} обязано содержать параметры предложения (offer)")

        offer = decision.offer
        db_offer = Offer(
            id=uuid.uuid4(),
            application_id=app.id,
            kind=offer.kind,
            amount_rub=offer.amount_rub,
            term_months=offer.term_months,
            rate_percent=offer.rate_percent,
            monthly_payment_rub=offer.monthly_payment_rub,
            valid_until=offer.valid_until,
            explanation=offer.explanation,
            state=OfferState.ACTIVE.value,
        )
        session.add(db_offer)

        target_status = (
            ApplicationStatus.OFFER if decision.outcome == "OFFER" else ApplicationStatus.COUNTER_OFFER
        )
        transition(
            session=session,
            application=app,
            to_status=target_status,
            actor_type=ActorType.SYSTEM,
            reason_code=reason_code,
            comment=decision.comment or "Предложение сформировано автоматически",
        )

    elif decision.outcome == "NEEDS_INFO":
        items = decision.info_request_items or ["Пояснение финансовой отчётности"]
        info_req = InfoRequest(
            id=uuid.uuid4(),
            application_id=app.id,
            round=app.info_rounds + 1,
            items=items,
            requested_by="SYSTEM",
        )
        session.add(info_req)
        transition(
            session=session,
            application=app,
            to_status=ApplicationStatus.NEEDS_INFO,
            actor_type=ActorType.SYSTEM,
            reason_code=reason_code,
            comment=decision.comment or f"Запрошены уточнения: {', '.join(items)}",
        )

    elif decision.outcome == "MANUAL_REVIEW":
        transition(
            session=session,
            application=app,
            to_status=ApplicationStatus.MANUAL_REVIEW,
            actor_type=ActorType.SYSTEM,
            reason_code=reason_code,
            comment=decision.comment or "Передано на рассмотрение специалисту банка",
        )

    elif decision.outcome == "REJECTED":
        transition(
            session=session,
            application=app,
            to_status=ApplicationStatus.REJECTED,
            actor_type=ActorType.SYSTEM,
            reason_code=reason_code or "LOW_SCORE",
            comment=decision.comment or "Отказ по результатам скоринговой оценки",
        )

    else:
        log.error("unrecognized_decision_outcome", extra={"outcome": decision.outcome})
        raise ValueError(f"Неизвестный исход кредитного решения: {decision.outcome}")

    complete_job(session, job)
