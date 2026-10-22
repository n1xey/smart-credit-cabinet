"""initial schema (DATA_MODEL v0.2)

Revision ID: 0001
Revises:
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

STATUSES = (
    "DRAFT SUBMITTED DATA_CHECK NEEDS_INFO ENRICHMENT SCORING MANUAL_REVIEW OFFER COUNTER_OFFER "
    "ACCEPTED SIGNING DISBURSED REJECTED CANCELLED EXPIRED"
).split()


def _pk():
    return sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()"))


def _ts(name, nullable=False, now=True):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable,
                     server_default=sa.text("now()") if now else None)


def upgrade() -> None:
    op.create_table(
        "users", _pk(),
        sa.Column("email", sa.Text, nullable=False, unique=True),
        sa.Column("full_name", sa.Text, nullable=False),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("role", sa.Text, nullable=False, server_default="CLIENT"),
        _ts("created_at"),
        sa.CheckConstraint("role IN ('CLIENT','OPERATOR','ADMIN')", name="ck_users_role"),
    )
    op.create_table(
        "companies", _pk(),
        sa.Column("owner_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("inn", sa.Text, nullable=False, unique=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("legal_form", sa.Text, nullable=False),
        sa.Column("registration_date", sa.Date),
        sa.Column("okved", sa.Text),
        sa.Column("address", sa.Text),
        _ts("created_at"),
        sa.CheckConstraint("legal_form IN ('OOO','IP')", name="ck_companies_legal_form"),
        sa.CheckConstraint(
            "(legal_form = 'OOO' AND length(inn) = 10) OR (legal_form = 'IP' AND length(inn) = 12)",
            name="ck_companies_inn_len"),
    )
    op.create_table(
        "products",
        sa.Column("code", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("min_amount_rub", sa.Integer, nullable=False),
        sa.Column("max_amount_rub", sa.Integer, nullable=False),
        sa.Column("min_term_months", sa.Integer, nullable=False),
        sa.Column("max_term_months", sa.Integer, nullable=False),
        sa.Column("base_rate_percent", sa.Numeric(5, 2), nullable=False),
        sa.Column("auto_limit_rub", sa.Integer, nullable=False),
        sa.Column("min_business_age_months", sa.Integer, nullable=False, server_default="0"),
        sa.Column("required_documents", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.create_table(
        "applications", _pk(),
        sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("product_code", sa.Text, sa.ForeignKey("products.code"), nullable=False),
        sa.Column("amount_rub", sa.Integer),
        sa.Column("term_months", sa.Integer),
        sa.Column("purpose", sa.Text),
        sa.Column("revenue_12m_rub", sa.BigInteger),
        sa.Column("net_profit_12m_rub", sa.BigInteger),
        sa.Column("existing_monthly_payments_rub", sa.BigInteger),
        sa.Column("status", sa.Text, nullable=False, server_default="DRAFT"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("idempotency_key", sa.Text, unique=True),
        sa.Column("assigned_operator_id", UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("info_rounds", sa.Integer, nullable=False, server_default="0"),
        _ts("submitted_at", nullable=True, now=False),
        _ts("expires_at", nullable=True, now=False),
        _ts("created_at"), _ts("updated_at"),
        sa.CheckConstraint("status IN (%s)" % ", ".join(repr(s) for s in STATUSES), name="ck_applications_status"),
    )
    op.create_index("ix_applications_status_updated", "applications", ["status", sa.text("updated_at DESC")])
    op.create_index("ix_applications_company", "applications", ["company_id"])

    op.create_table(
        "application_status_history", _pk(),
        sa.Column("application_id", UUID(as_uuid=True), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("from_status", sa.Text),
        sa.Column("to_status", sa.Text, nullable=False),
        sa.Column("actor_type", sa.Text, nullable=False),
        sa.Column("actor_id", sa.Text),
        sa.Column("reason_code", sa.Text),
        sa.Column("comment", sa.Text),
        _ts("created_at"),
        sa.CheckConstraint("actor_type IN ('CLIENT','OPERATOR','SYSTEM')", name="ck_history_actor_type"),
    )
    op.create_index("ix_history_app_created", "application_status_history", ["application_id", "created_at"])

    op.create_table(
        "documents", _pk(),
        sa.Column("application_id", UUID(as_uuid=True), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("doc_type", sa.Text, nullable=False),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("storage_path", sa.Text, nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("sha256", sa.Text, nullable=False),
        sa.Column("mime_type", sa.Text),
        _ts("uploaded_at"),
    )
    op.create_table(
        "enrichment_results", _pk(),
        sa.Column("application_id", UUID(as_uuid=True), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("payload", JSONB),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="1"),
        _ts("fetched_at"),
        sa.CheckConstraint("source IN ('BKI','EGRUL')", name="ck_enrichment_source"),
        sa.CheckConstraint("status IN ('OK','FAILED')", name="ck_enrichment_status"),
    )
    op.create_index("ix_enrichment_app_source", "enrichment_results", ["application_id", "source"])

    op.create_table(
        "scoring_results", _pk(),
        sa.Column("application_id", UUID(as_uuid=True), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("score", sa.Integer, nullable=False),
        sa.Column("grade", sa.Text, nullable=False),
        sa.Column("factors", JSONB, nullable=False),
        sa.Column("knockouts", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("model_version", sa.Text, nullable=False),
        _ts("created_at"),
    )
    op.create_table(
        "decisions", _pk(),
        sa.Column("application_id", UUID(as_uuid=True), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("outcome", sa.Text, nullable=False),
        sa.Column("decided_by", sa.Text, nullable=False),
        sa.Column("decided_by_id", sa.Text),
        sa.Column("reason_codes", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("comment", sa.Text),
        _ts("created_at"),
        sa.CheckConstraint(
            "outcome IN ('OFFER','COUNTER_OFFER','MANUAL_REVIEW','NEEDS_INFO','REJECTED')", name="ck_decisions_outcome"),
        sa.CheckConstraint("decided_by IN ('SYSTEM','OPERATOR')", name="ck_decisions_decided_by"),
    )
    op.create_table(
        "offers", _pk(),
        sa.Column("application_id", UUID(as_uuid=True), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("amount_rub", sa.Integer, nullable=False),
        sa.Column("term_months", sa.Integer, nullable=False),
        sa.Column("rate_percent", sa.Numeric(5, 2), nullable=False),
        sa.Column("monthly_payment_rub", sa.Integer, nullable=False),
        sa.Column("explanation", sa.Text),
        _ts("valid_until", now=False),
        sa.Column("state", sa.Text, nullable=False, server_default="ACTIVE"),
        _ts("created_at"),
        sa.CheckConstraint("kind IN ('ORIGINAL','COUNTER')", name="ck_offers_kind"),
        sa.CheckConstraint("state IN ('ACTIVE','ACCEPTED','DECLINED','EXPIRED')", name="ck_offers_state"),
    )
    op.create_index("uq_offers_one_active", "offers", ["application_id"], unique=True,
                    postgresql_where=sa.text("state = 'ACTIVE'"))

    op.create_table(
        "info_requests", _pk(),
        sa.Column("application_id", UUID(as_uuid=True), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("round", sa.Integer, nullable=False, server_default="1"),
        sa.Column("items", JSONB, nullable=False),
        sa.Column("response", JSONB),
        sa.Column("requested_by", sa.Text, nullable=False),
        _ts("created_at"),
        _ts("answered_at", nullable=True, now=False),
    )
    op.create_table(
        "jobs", _pk(),
        sa.Column("application_id", UUID(as_uuid=True), sa.ForeignKey("applications.id")),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("step_key", sa.Text, nullable=False, server_default=""),
        sa.Column("payload", JSONB),
        sa.Column("state", sa.Text, nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        _ts("run_after"),
        _ts("locked_at", nullable=True, now=False),
        sa.Column("last_error", sa.Text),
        _ts("created_at"), _ts("updated_at"),
        sa.UniqueConstraint("application_id", "type", "step_key", name="uq_jobs_app_type_step"),
        sa.CheckConstraint("state IN ('PENDING','RUNNING','DONE','FAILED')", name="ck_jobs_state"),
    )
    op.create_index("ix_jobs_state_run_after", "jobs", ["state", "run_after"])


def downgrade() -> None:
    for t in ("jobs", "info_requests", "offers", "decisions", "scoring_results", "enrichment_results",
              "documents", "application_status_history", "applications", "products", "companies", "users"):
        op.drop_table(t)
