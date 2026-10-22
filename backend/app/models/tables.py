"""Модели по docs/DATA_MODEL.md (v0.2). Миграция 0001 написана вручную и должна совпадать с этим файлом."""
import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger, CheckConstraint, Date, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import DateTime

from app.enums import ApplicationStatus


def _in(column: str, enum_cls) -> str:
    return f"{column} IN ({', '.join(repr(e.value) for e in enum_cls)})"


class Base(DeclarativeBase):
    pass


_PK = dict(primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
_NOW = dict(server_default=text("now()"))


def _ts(**kw):
    return mapped_column(DateTime(timezone=True), **kw)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('CLIENT','OPERATOR','ADMIN')", name="ck_users_role"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_PK)
    email: Mapped[str] = mapped_column(Text, unique=True)
    full_name: Mapped[str] = mapped_column(Text)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text, default="CLIENT")
    created_at: Mapped[datetime] = _ts(**_NOW)


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (
        CheckConstraint("legal_form IN ('OOO','IP')", name="ck_companies_legal_form"),
        CheckConstraint(
            "(legal_form = 'OOO' AND length(inn) = 10) OR (legal_form = 'IP' AND length(inn) = 12)",
            name="ck_companies_inn_len",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_PK)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), unique=True)  # 1 компания на пользователя
    inn: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    legal_form: Mapped[str] = mapped_column(Text)
    registration_date: Mapped[date | None] = mapped_column(Date)
    okved: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts(**_NOW)


class Product(Base):
    __tablename__ = "products"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    min_amount_rub: Mapped[int] = mapped_column(Integer)
    max_amount_rub: Mapped[int] = mapped_column(Integer)
    min_term_months: Mapped[int] = mapped_column(Integer)
    max_term_months: Mapped[int] = mapped_column(Integer)
    base_rate_percent: Mapped[float] = mapped_column(Numeric(5, 2))
    auto_limit_rub: Mapped[int] = mapped_column(Integer)
    min_business_age_months: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    required_documents: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        CheckConstraint(_in("status", ApplicationStatus), name="ck_applications_status"),
        Index("ix_applications_status_updated", "status", text("updated_at DESC")),
        Index("ix_applications_company", "company_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_PK)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    product_code: Mapped[str] = mapped_column(ForeignKey("products.code"))
    amount_rub: Mapped[int | None] = mapped_column(Integer)
    term_months: Mapped[int | None] = mapped_column(Integer)
    purpose: Mapped[str | None] = mapped_column(Text)
    revenue_12m_rub: Mapped[int | None] = mapped_column(BigInteger)
    net_profit_12m_rub: Mapped[int | None] = mapped_column(BigInteger)
    existing_monthly_payments_rub: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(Text, default="DRAFT", server_default="DRAFT")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")  # оптимистичная блокировка
    idempotency_key: Mapped[str | None] = mapped_column(Text, unique=True)
    assigned_operator_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    info_rounds: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    submitted_at: Mapped[datetime | None] = _ts()
    expires_at: Mapped[datetime | None] = _ts()
    created_at: Mapped[datetime] = _ts(**_NOW)
    updated_at: Mapped[datetime] = _ts(**_NOW)


class ApplicationStatusHistory(Base):
    __tablename__ = "application_status_history"
    __table_args__ = (
        CheckConstraint("actor_type IN ('CLIENT','OPERATOR','SYSTEM')", name="ck_history_actor_type"),
        Index("ix_history_app_created", "application_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_PK)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"))
    from_status: Mapped[str | None] = mapped_column(Text)
    to_status: Mapped[str] = mapped_column(Text)
    actor_type: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[str | None] = mapped_column(Text)
    reason_code: Mapped[str | None] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts(**_NOW)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_PK)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"))
    doc_type: Mapped[str] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(Text)
    storage_path: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str | None] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = _ts(**_NOW)


class EnrichmentResult(Base):
    __tablename__ = "enrichment_results"
    __table_args__ = (
        CheckConstraint("source IN ('BKI','EGRUL')", name="ck_enrichment_source"),
        CheckConstraint("status IN ('OK','FAILED')", name="ck_enrichment_status"),
        Index("ix_enrichment_app_source", "application_id", "source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_PK)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"))
    source: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    fetched_at: Mapped[datetime] = _ts(**_NOW)


class ScoringResult(Base):
    __tablename__ = "scoring_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_PK)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"))
    score: Mapped[int] = mapped_column(Integer)
    grade: Mapped[str] = mapped_column(Text)
    factors: Mapped[list] = mapped_column(JSONB)
    knockouts: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    model_version: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts(**_NOW)  # актуальной считается последняя запись


class Decision(Base):
    __tablename__ = "decisions"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('OFFER','COUNTER_OFFER','MANUAL_REVIEW','NEEDS_INFO','REJECTED')", name="ck_decisions_outcome"
        ),
        CheckConstraint("decided_by IN ('SYSTEM','OPERATOR')", name="ck_decisions_decided_by"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_PK)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"))
    outcome: Mapped[str] = mapped_column(Text)
    decided_by: Mapped[str] = mapped_column(Text)
    decided_by_id: Mapped[str | None] = mapped_column(Text)
    reason_codes: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts(**_NOW)


class Offer(Base):
    __tablename__ = "offers"
    __table_args__ = (
        CheckConstraint("kind IN ('ORIGINAL','COUNTER')", name="ck_offers_kind"),
        CheckConstraint("state IN ('ACTIVE','ACCEPTED','DECLINED','EXPIRED')", name="ck_offers_state"),
        Index("uq_offers_one_active", "application_id", unique=True, postgresql_where=text("state = 'ACTIVE'")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_PK)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"))
    kind: Mapped[str] = mapped_column(Text)
    amount_rub: Mapped[int] = mapped_column(Integer)
    term_months: Mapped[int] = mapped_column(Integer)
    rate_percent: Mapped[float] = mapped_column(Numeric(5, 2))
    monthly_payment_rub: Mapped[int] = mapped_column(Integer)
    explanation: Mapped[str | None] = mapped_column(Text)
    valid_until: Mapped[datetime] = _ts()
    state: Mapped[str] = mapped_column(Text, default="ACTIVE", server_default="ACTIVE")
    created_at: Mapped[datetime] = _ts(**_NOW)


class InfoRequest(Base):
    __tablename__ = "info_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_PK)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"))
    round: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    items: Mapped[list] = mapped_column(JSONB)
    response: Mapped[dict | None] = mapped_column(JSONB)
    requested_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts(**_NOW)
    answered_at: Mapped[datetime | None] = _ts()


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("application_id", "type", "step_key", name="uq_jobs_app_type_step"),
        CheckConstraint("state IN ('PENDING','RUNNING','DONE','FAILED')", name="ck_jobs_state"),
        Index("ix_jobs_state_run_after", "state", "run_after"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_PK)
    application_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("applications.id"))
    type: Mapped[str] = mapped_column(Text)
    step_key: Mapped[str] = mapped_column(Text, default="", server_default="")
    payload: Mapped[dict | None] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(Text, default="PENDING", server_default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    run_after: Mapped[datetime] = _ts(**_NOW)
    locked_at: Mapped[datetime | None] = _ts()
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts(**_NOW)
    updated_at: Mapped[datetime] = _ts(**_NOW)
