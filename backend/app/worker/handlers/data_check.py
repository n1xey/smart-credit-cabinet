"""Обработчик шага data_check кредитного конвейера.

Выполняет:
1. Внутренний переход SUBMITTED -> DATA_CHECK с enqueue_jobs=False (без дублирования задачи в очереди).
2. Валидацию контрольной суммы ИНН (ФНС РФ) -> отказ INVALID_INN при ошибке.
3. Проверку возраста бизнеса для выбранного продукта -> отказ PRODUCT_NOT_AVAILABLE при несоответствии.
4. Проверку наличия обязательных документов продукта -> запрос уточнений NEEDS_INFO при отсутствии.
5. При успешном прохождении всех проверок -> перевод в ENRICHMENT (автоматически ставит задачу enrichment).
"""
from datetime import datetime, timezone
import logging
import uuid

from sqlalchemy.orm import Session

from app.enums import ActorType, ApplicationStatus
from app.models.tables import Application, Company, Document, InfoRequest, Job, Product
from app.services.inn_validator import is_valid_inn
from app.state_machine import transition
from app.worker.deps import WorkerDeps
from app.worker.queue import complete_job

log = logging.getLogger("app.worker.handlers.data_check")


from datetime import date, datetime, timezone


def _calculate_business_age_months(reg_date_val: date | str | None) -> int:
    """Вычисляет возраст бизнеса в месяцах по объекту date или строке (ГГГГ-ММ-ДД)."""
    if not reg_date_val:
        return 0
    if isinstance(reg_date_val, str):
        try:
            parsed_date = datetime.strptime(reg_date_val[:10], "%Y-%m-%d").date()
        except Exception:
            log.warning("invalid_registration_date_format", extra={"reg_date": reg_date_val})
            return 0
    else:
        parsed_date = reg_date_val

    today = datetime.now(timezone.utc).date()
    return (today.year - parsed_date.year) * 12 + (today.month - parsed_date.month)


def handle_data_check(session: Session, job: Job, deps: WorkerDeps) -> None:
    """Выполняет первичную проверку данных заявки."""
    app = (
        session.query(Application)
        .filter(Application.id == job.application_id)
        .with_for_update()
        .first()
    )
    if app is None:
        log.warning("data_check_application_not_found", extra={"application_id": str(job.application_id)})
        complete_job(session, job)
        return

    # 1. Внутренний переход SUBMITTED -> DATA_CHECK с enqueue_jobs=False,
    # чтобы не плодить вторую задачу data_check на шаг DATA_CHECK
    if app.status == ApplicationStatus.SUBMITTED.value:
        transition(
            session=session,
            application=app,
            to_status=ApplicationStatus.DATA_CHECK,
            actor_type=ActorType.SYSTEM,
            actor_id=None,
            actor_role="SYSTEM",
            enqueue_jobs=False,
            comment="Автоматический переход к первичным проверкам",
        )

    company = session.query(Company).filter(Company.id == app.company_id).first()
    if company is None:
        log.error("data_check_company_not_found", extra={"company_id": str(app.company_id)})
        transition(
            session=session,
            application=app,
            to_status=ApplicationStatus.REJECTED,
            actor_type=ActorType.SYSTEM,
            reason_code="INVALID_INN",
            comment="Компания по заявке не найдена",
        )
        complete_job(session, job)
        return

    # 2. Проверка валидности ИНН компании (формат и контрольная сумма ФНС)
    if not is_valid_inn(company.inn, company.legal_form):
        transition(
            session=session,
            application=app,
            to_status=ApplicationStatus.REJECTED,
            actor_type=ActorType.SYSTEM,
            reason_code="INVALID_INN",
            comment="ИНН компании не прошёл проверку контрольной суммы ФНС РФ",
        )
        complete_job(session, job)
        return

    # 3. Проверка возраста бизнеса для выбранного кредитного продукта
    product = session.query(Product).filter(Product.code == app.product_code).first()
    if product is not None and product.min_business_age_months > 0:
        age_months = _calculate_business_age_months(company.registration_date)
        if age_months < product.min_business_age_months:
            transition(
                session=session,
                application=app,
                to_status=ApplicationStatus.REJECTED,
                actor_type=ActorType.SYSTEM,
                reason_code="PRODUCT_NOT_AVAILABLE",
                comment=(
                    f"Возраст бизнеса ({age_months} мес.) меньше минимального "
                    f"для продукта {product.name} ({product.min_business_age_months} мес.)"
                ),
            )
            complete_job(session, job)
            return

    # 4. Проверка обязательных документов по продукту
    if product is not None and product.required_documents:
        uploaded_docs = session.query(Document).filter(Document.application_id == app.id).all()
        uploaded_types = {d.doc_type for d in uploaded_docs}
        missing_docs = [req for req in product.required_documents if req not in uploaded_types]

        if missing_docs:
            info_req = InfoRequest(
                id=uuid.uuid4(),
                application_id=app.id,
                round=app.info_rounds + 1,
                items=missing_docs,
                requested_by="SYSTEM",
            )
            session.add(info_req)
            transition(
                session=session,
                application=app,
                to_status=ApplicationStatus.NEEDS_INFO,
                actor_type=ActorType.SYSTEM,
                reason_code="MISSING_DOCUMENTS",
                comment=f"Не загружены обязательные документы: {', '.join(missing_docs)}",
            )
            complete_job(session, job)
            return

    # 5. Все проверки пройдены -> переход к обогащению (ставит задачу enrichment)
    transition(
        session=session,
        application=app,
        to_status=ApplicationStatus.ENRICHMENT,
        actor_type=ActorType.SYSTEM,
        comment="Первичные проверки успешно пройдены",
    )
    complete_job(session, job)
