"""Общие pytest-фикстуры.

Для тестов, не требующих БД: используем TestClient напрямую.
Для тестов auth и API: поднимаем SQLite in-memory, подменяем get_db / get_engine.
SQLite не поддерживает JSONB и PostgreSQL-специфичные CheckConstraints —
поэтому для тестовой схемы используем отдельный MetaData с JSON вместо JSONB
и без CHECK-ограничений.
"""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Session, sessionmaker

from app.auth.security import create_access_token, hash_password
from app.enums import Role
from app.main import create_app
from app.models.tables import User


# ---------------------------------------------------------------------------
# Базовые фикстуры без БД (используются test_skeleton.py)
# ---------------------------------------------------------------------------
@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# SQLite-совместимая тестовая схема (JSON вместо JSONB, без PG-CHECK)
# ---------------------------------------------------------------------------
def _build_test_metadata() -> MetaData:
    """Воссоздаёт схему БД без PostgreSQL-специфики для SQLite."""
    meta = MetaData()

    _PK = dict(primary_key=True)
    _NOW = dict(server_default=text("CURRENT_TIMESTAMP"))

    def _ts(**kw):
        from sqlalchemy import DateTime
        return kw  # используем keyword-only для mapped_column

    Table(
        "users", meta,
        *[
            __import__("sqlalchemy", fromlist=["Column"]).Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
            __import__("sqlalchemy", fromlist=["Column"]).Column("email", Text, unique=True, nullable=False),
            __import__("sqlalchemy", fromlist=["Column"]).Column("full_name", Text, nullable=False),
            __import__("sqlalchemy", fromlist=["Column"]).Column("password_hash", Text, nullable=False),
            __import__("sqlalchemy", fromlist=["Column"]).Column("role", Text, nullable=False, server_default="CLIENT"),
            __import__("sqlalchemy", fromlist=["Column"]).Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
        ],
    )

    return meta


# Проще: переиспользуем модели SQLAlchemy напрямую, но заменяем JSONB на JSON через event
@pytest.fixture(scope="session")
def _sqlite_engine():
    """Создаёт in-memory SQLite с патченными типами."""
    from sqlalchemy import event as sa_event
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.types import JSON, TypeDecorator

    # Подменяем JSONB на JSON для SQLite
    class _JsonCompat(TypeDecorator):
        impl = JSON
        cache_ok = True

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    @sa_event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    # Создаём SQLite-совместимую копию схемы вручную
    from sqlalchemy import Column, DateTime
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID

    test_meta = MetaData()

    col = Column

    Table("users", test_meta,
        col("id", Text, primary_key=True, default=lambda: str(uuid.uuid4())),
        col("email", Text, unique=True, nullable=False),
        col("full_name", Text, nullable=False),
        col("password_hash", Text, nullable=False),
        col("role", Text, nullable=False, server_default=text("'CLIENT'")),
        col("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    )
    Table("companies", test_meta,
        col("id", Text, primary_key=True, default=lambda: str(uuid.uuid4())),
        col("owner_id", Text, ForeignKey("users.id"), unique=True),
        col("inn", Text, unique=True, nullable=False),
        col("name", Text, nullable=False),
        col("legal_form", Text, nullable=False),
        col("registration_date", Text),
        col("okved", Text),
        col("address", Text),
        col("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    )
    Table("products", test_meta,
        col("code", Text, primary_key=True),
        col("name", Text, nullable=False),
        col("description", Text),
        col("min_amount_rub", Integer, nullable=False),
        col("max_amount_rub", Integer, nullable=False),
        col("min_term_months", Integer, nullable=False),
        col("max_term_months", Integer, nullable=False),
        col("base_rate_percent", Numeric(5, 2), nullable=False),
        col("auto_limit_rub", Integer, nullable=False),
        col("min_business_age_months", Integer, server_default=text("0")),
        col("required_documents", JSON, server_default=text("'[]'")),
    )
    Table("applications", test_meta,
        col("id", Text, primary_key=True, default=lambda: str(uuid.uuid4())),
        col("company_id", Text, ForeignKey("companies.id"), nullable=False),
        col("created_by", Text, ForeignKey("users.id"), nullable=False),
        col("product_code", Text, ForeignKey("products.code"), nullable=False),
        col("amount_rub", Integer),
        col("term_months", Integer),
        col("purpose", Text),
        col("revenue_12m_rub", BigInteger),
        col("net_profit_12m_rub", BigInteger),
        col("existing_monthly_payments_rub", BigInteger),
        col("status", Text, nullable=False, server_default=text("'DRAFT'")),
        col("version", Integer, nullable=False, server_default=text("1")),
        col("idempotency_key", Text, unique=True),
        col("assigned_operator_id", Text, ForeignKey("users.id")),
        col("info_rounds", Integer, nullable=False, server_default=text("0")),
        col("submitted_at", Text),
        col("expires_at", Text),
        col("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
        col("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    )
    Table("application_status_history", test_meta,
        col("id", Text, primary_key=True, default=lambda: str(uuid.uuid4())),
        col("application_id", Text, ForeignKey("applications.id"), nullable=False),
        col("from_status", Text),
        col("to_status", Text, nullable=False),
        col("actor_type", Text, nullable=False),
        col("actor_id", Text),
        col("reason_code", Text),
        col("comment", Text),
        col("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    )
    Table("documents", test_meta,
        col("id", Text, primary_key=True, default=lambda: str(uuid.uuid4())),
        col("application_id", Text, ForeignKey("applications.id"), nullable=False),
        col("doc_type", Text, nullable=False),
        col("filename", Text, nullable=False),
        col("storage_path", Text, nullable=False),
        col("size_bytes", Integer, nullable=False),
        col("sha256", Text, nullable=False),
        col("mime_type", Text),
        col("uploaded_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    )
    Table("enrichment_results", test_meta,
        col("id", Text, primary_key=True, default=lambda: str(uuid.uuid4())),
        col("application_id", Text, ForeignKey("applications.id"), nullable=False),
        col("source", Text, nullable=False),
        col("payload", JSON),
        col("status", Text, nullable=False),
        col("attempts", Integer, nullable=False, server_default=text("1")),
        col("fetched_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    )
    Table("scoring_results", test_meta,
        col("id", Text, primary_key=True, default=lambda: str(uuid.uuid4())),
        col("application_id", Text, ForeignKey("applications.id"), nullable=False),
        col("score", Integer, nullable=False),
        col("grade", Text, nullable=False),
        col("factors", JSON, nullable=False),
        col("knockouts", JSON, server_default=text("'[]'")),
        col("model_version", Text, nullable=False),
        col("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    )
    Table("decisions", test_meta,
        col("id", Text, primary_key=True, default=lambda: str(uuid.uuid4())),
        col("application_id", Text, ForeignKey("applications.id"), nullable=False),
        col("outcome", Text, nullable=False),
        col("decided_by", Text, nullable=False),
        col("decided_by_id", Text),
        col("reason_codes", JSON, server_default=text("'[]'")),
        col("comment", Text),
        col("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    )
    Table("offers", test_meta,
        col("id", Text, primary_key=True, default=lambda: str(uuid.uuid4())),
        col("application_id", Text, ForeignKey("applications.id"), nullable=False),
        col("kind", Text, nullable=False),
        col("amount_rub", Integer, nullable=False),
        col("term_months", Integer, nullable=False),
        col("rate_percent", Numeric(5, 2), nullable=False),
        col("monthly_payment_rub", Integer, nullable=False),
        col("explanation", Text),
        col("valid_until", Text, nullable=False),
        col("state", Text, nullable=False, server_default=text("'ACTIVE'")),
        col("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    )
    Table("info_requests", test_meta,
        col("id", Text, primary_key=True, default=lambda: str(uuid.uuid4())),
        col("application_id", Text, ForeignKey("applications.id"), nullable=False),
        col("round", Integer, nullable=False, server_default=text("1")),
        col("items", JSON, nullable=False),
        col("response", JSON),
        col("requested_by", Text, nullable=False),
        col("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
        col("answered_at", Text),
    )
    Table("jobs", test_meta,
        col("id", Text, primary_key=True, default=lambda: str(uuid.uuid4())),
        col("application_id", Text, ForeignKey("applications.id")),
        col("type", Text, nullable=False),
        col("step_key", Text, nullable=False, server_default=text("''")),
        col("payload", JSON),
        col("state", Text, nullable=False, server_default=text("'PENDING'")),
        col("attempts", Integer, nullable=False, server_default=text("0")),
        col("run_after", Text, server_default=text("CURRENT_TIMESTAMP")),
        col("locked_at", Text),
        col("last_error", Text),
        col("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
        col("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
        UniqueConstraint("application_id", "type", "step_key", name="uq_jobs_app_type_step"),
    )

    test_meta.create_all(engine)
    return engine


@pytest.fixture
def db_session(_sqlite_engine):
    """Чистая транзакция на каждый тест (откат после теста)."""
    SessionLocal = sessionmaker(bind=_sqlite_engine, expire_on_commit=False)
    connection = _sqlite_engine.connect()
    transaction = connection.begin()
    session = SessionLocal(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def app_with_db(db_session):
    """Приложение с подменённой зависимостью get_db → тестовая SQLite-сессия."""
    from app.db import get_db

    application = create_app()
    application.dependency_overrides[get_db] = lambda: db_session
    return application


@pytest.fixture
def api_client(app_with_db):
    return TestClient(app_with_db, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Вспомогательные фикстуры: пользователи
# ---------------------------------------------------------------------------
def _make_user(db: Session, email: str, role: str, full_name: str = "Test User") -> User:
    user = User(
        email=email,
        full_name=full_name,
        password_hash=hash_password("Password1!"),
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def client_user(db_session) -> User:
    return _make_user(db_session, "client@example.com", Role.CLIENT.value)


@pytest.fixture
def operator_user(db_session) -> User:
    return _make_user(db_session, "operator@example.com", Role.OPERATOR.value, "Operator User")


def auth_headers(user: User) -> dict:
    """Возвращает заголовок Authorization с валидным JWT для данного пользователя."""
    token = create_access_token(user.id, user.role, user.email)
    return {"Authorization": f"Bearer {token}"}
