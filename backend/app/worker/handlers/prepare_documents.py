"""Обработчик шага prepare_documents кредитного конвейера.

Выполняет:
1. Загрузку принятого предложения (Offer со state=ACCEPTED) и реквизитов компании.
2. Формирование текста кредитного соглашения (credit_agreement.txt) без сторонних библиотек.
3. Сохранение файла в директорию uploads_dir / {application_id} и расчёт SHA-256.
4. Добавление записи в таблицу documents (doc_type='OTHER', mime_type='text/plain; charset=utf-8').
5. Перевод заявки в SIGNING с актором SYSTEM.
"""
from datetime import datetime, timezone
import hashlib
import logging
import uuid

from sqlalchemy.orm import Session

from app.enums import ActorType, ApplicationStatus, DocType, OfferState
from app.models.tables import Application, Company, Document, Job, Offer
from app.state_machine import transition
from app.worker.deps import WorkerDeps
from app.worker.queue import complete_job

log = logging.getLogger("app.worker.handlers.prepare_documents")


def handle_prepare_documents(session: Session, job: Job, deps: WorkerDeps) -> None:
    """Формирует пакет документов для подписания клиентом."""
    app = (
        session.query(Application)
        .filter(Application.id == job.application_id)
        .with_for_update()
        .first()
    )
    if app is None:
        log.warning("prepare_documents_app_not_found", extra={"application_id": str(job.application_id)})
        complete_job(session, job)
        return

    company = session.query(Company).filter(Company.id == app.company_id).first()
    if company is None:
        log.error("prepare_documents_company_not_found", extra={"company_id": str(app.company_id)})
        complete_job(session, job)
        return

    # Находим принятый оффер (или активный/последний для надёжности)
    offer = (
        session.query(Offer)
        .filter(
            Offer.application_id == app.id,
            Offer.state == OfferState.ACCEPTED.value,
        )
        .order_by(Offer.created_at.desc())
        .first()
    )
    if offer is None:
        offer = (
            session.query(Offer)
            .filter(Offer.application_id == app.id)
            .order_by(Offer.created_at.desc())
            .first()
        )

    amount = offer.amount_rub if offer else (app.amount_rub or 0)
    term = offer.term_months if offer else (app.term_months or 0)
    rate = offer.rate_percent if offer else 15.0
    monthly = offer.monthly_payment_rub if offer else 0

    now_utc = datetime.now(timezone.utc)
    agreement_text = (
        f"КРЕДИТНЫЙ ДОГОВОР № {app.id}\n"
        f"Заёмщик: {company.name} (ИНН: {company.inn})\n"
        f"Сумма кредита: {amount:,} руб.\n"
        f"Срок кредитования: {term} мес.\n"
        f"Процентная ставка: {rate}%\n"
        f"Ежемесячный платёж: {monthly:,} руб.\n"
        f"Дата формирования пакета документов: {now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        "Документ сформирован автоматически кредитным конвейером и готов к подписанию клиентом.\n"
    )
    content_bytes = agreement_text.encode("utf-8")
    sha256 = hashlib.sha256(content_bytes).hexdigest()

    # Сохраняем в uploads_dir
    app_folder = deps.uploads_dir / str(app.id)
    app_folder.mkdir(parents=True, exist_ok=True)
    doc_id = uuid.uuid4()
    file_path = app_folder / f"{doc_id}_credit_agreement.txt"
    file_path.write_bytes(content_bytes)

    # Сохраняем запись о документе
    doc = Document(
        id=doc_id,
        application_id=app.id,
        doc_type=DocType.OTHER.value,
        filename="credit_agreement.txt",
        storage_path=str(file_path),
        size_bytes=len(content_bytes),
        sha256=sha256,
        mime_type="text/plain; charset=utf-8",
    )
    session.add(doc)

    # Переводим в SIGNING
    transition(
        session=session,
        application=app,
        to_status=ApplicationStatus.SIGNING,
        actor_type=ActorType.SYSTEM,
        comment="Пакет документов сформирован, ожидается подписание клиентом",
    )
    complete_job(session, job)
