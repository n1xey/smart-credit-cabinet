"""Исчерпывающие тесты для автомата состояний (State Machine).

Покрывают:
1. Полноту графа переходов (все 29 валидных переходов из STATE_MACHINE.md)
2. Запрет невалидных переходов и переходов из финальных статусов (409 INVALID_TRANSITION)
3. Авторизацию акторов и проверку владения (404 NOT_FOUND для чужих заявок, 403/409 для несоответствий)
4. Оптимистичную блокировку по version (409 VERSION_CONFLICT)
5. Аудит всех переходов в application_status_history
6. Логику назначения оператора (take_in_review, 409 CONFLICT, идемпотентность)
7. Ограничение раундов уточнений (MAX_INFO_ROUNDS -> эскалация в MANUAL_REVIEW с INFO_ROUNDS_EXCEEDED)
8. Расчёт дедлайнов expires_at и submitted_at
9. Синхронизацию статусов офферов (ACCEPTED, DECLINED, EXPIRED)
10. Постановку задач в очередь jobs
11. Идемпотентность системных повторов (SYSTEM)
12. Вспомогательную функцию get_allowed_transitions
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.enums import ActorType, ApplicationStatus, ErrorCode, OfferState, Role
from app.errors import ApiError
from app.models.tables import (
    Application,
    ApplicationStatusHistory,
    Company,
    Job,
    Offer,
    Product,
    User,
)
from app.state_machine import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATUSES,
    get_allowed_transitions,
    take_in_review,
    transition,
)


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------
@pytest.fixture
def product(db_session: Session) -> Product:
    p = Product(
        code="WORKING_CAPITAL",
        name="Оборотный кредит",
        description="Кредит на пополнение оборотных средств",
        min_amount_rub=300_000,
        max_amount_rub=10_000_000,
        min_term_months=3,
        max_term_months=24,
        base_rate_percent=18.0,
        auto_limit_rub=3_000_000,
        min_business_age_months=0,
        required_documents=[],
    )
    db_session.add(p)
    db_session.commit()
    return p


@pytest.fixture
def company(db_session: Session, client_user: User) -> Company:
    c = Company(
        owner_id=client_user.id,
        inn="0000000001",
        name='ООО "Ромашка"',
        legal_form="OOO",
    )
    db_session.add(c)
    db_session.commit()
    return c


@pytest.fixture
def other_client(db_session: Session) -> User:
    from tests.conftest import _make_user

    return _make_user(db_session, "other_client@example.com", Role.CLIENT.value, "Other Client")


@pytest.fixture
def other_operator(db_session: Session) -> User:
    from tests.conftest import _make_user

    return _make_user(db_session, "other_operator@example.com", Role.OPERATOR.value, "Other Operator")


def create_application(
    db: Session,
    company: Company,
    user: User,
    product: Product,
    status: ApplicationStatus = ApplicationStatus.DRAFT,
    version: int = 1,
    info_rounds: int = 0,
    assigned_operator_id: uuid.UUID | None = None,
) -> Application:
    app = Application(
        company_id=company.id,
        created_by=user.id,
        product_code=product.code,
        amount_rub=1_000_000,
        term_months=12,
        purpose="Пополнение оборотных средств",
        status=status.value,
        version=version,
        info_rounds=info_rounds,
        assigned_operator_id=assigned_operator_id,
    )
    db.add(app)
    db.commit()
    db.refresh(app)
    return app


# ---------------------------------------------------------------------------
# 1. Полнота графа переходов (все 29 валидных переходов)
# ---------------------------------------------------------------------------
def test_all_transitions_defined():
    """Проверяем, что в графе ровно 30 переходов (29 по базовой диаграмме + 1 эскалация раундов по правилу 7)."""
    assert len(ALLOWED_TRANSITIONS) == 30


@pytest.mark.parametrize("rule", ALLOWED_TRANSITIONS, ids=lambda r: f"{r.from_status}->{r.to_status}")
def test_each_valid_transition_executes_successfully(
    rule, db_session: Session, company: Company, client_user: User, operator_user: User, product: Product
):
    """Каждый из 29 переходов успешно выполняется соответствующим актором."""
    actor_type = next(iter(rule.allowed_actors))
    actor_id = client_user.id if actor_type == ActorType.CLIENT else operator_user.id
    actor_role = Role.CLIENT.value if actor_type == ActorType.CLIENT else Role.OPERATOR.value

    # Если переход из MANUAL_REVIEW, назначаем оператора заранее
    assigned_op = operator_user.id if rule.from_status == ApplicationStatus.MANUAL_REVIEW else None

    app = create_application(
        db_session,
        company,
        client_user,
        product,
        status=rule.from_status,
        assigned_operator_id=assigned_op,
    )

    updated = transition(
        session=db_session,
        application=app,
        to_status=rule.to_status,
        actor_type=actor_type,
        actor_id=actor_id,
        actor_role=actor_role,
        reason_code="TEST_REASON",
        comment="Unit test",
    )

    assert updated.status == rule.to_status.value
    assert updated.version == 2

    # Проверяем запись в истории
    hist = (
        db_session.query(ApplicationStatusHistory)
        .filter_by(application_id=app.id)
        .order_by(ApplicationStatusHistory.created_at.desc())
        .first()
    )
    assert hist is not None
    assert hist.from_status == rule.from_status.value
    assert hist.to_status == rule.to_status.value
    assert hist.actor_type == actor_type.value
    assert hist.reason_code == "TEST_REASON"


# ---------------------------------------------------------------------------
# 2. Запрет невалидных переходов и переходов из терминальных статусов
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        (ApplicationStatus.DRAFT, ApplicationStatus.DISBURSED),
        (ApplicationStatus.DRAFT, ApplicationStatus.SCORING),
        (ApplicationStatus.SUBMITTED, ApplicationStatus.OFFER),
        (ApplicationStatus.DATA_CHECK, ApplicationStatus.DISBURSED),
        (ApplicationStatus.ENRICHMENT, ApplicationStatus.DISBURSED),
        (ApplicationStatus.SCORING, ApplicationStatus.SIGNING),
        (ApplicationStatus.ACCEPTED, ApplicationStatus.DRAFT),
    ],
)
def test_invalid_transition_raises_409(
    from_status, to_status, db_session: Session, company: Company, client_user: User, product: Product
):
    app = create_application(db_session, company, client_user, product, status=from_status)

    with pytest.raises(ApiError) as exc_info:
        transition(
            session=db_session,
            application=app,
            to_status=to_status,
            actor_type=ActorType.SYSTEM,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == ErrorCode.INVALID_TRANSITION


@pytest.mark.parametrize("terminal_status", list(TERMINAL_STATUSES))
def test_transitions_from_terminal_statuses_forbidden(
    terminal_status, db_session: Session, company: Company, client_user: User, product: Product
):
    app = create_application(db_session, company, client_user, product, status=terminal_status)

    for target in ApplicationStatus:
        with pytest.raises(ApiError) as exc_info:
            transition(
                session=db_session,
                application=app,
                to_status=target,
                actor_type=ActorType.SYSTEM,
            )
        assert exc_info.value.status_code == 409
        assert exc_info.value.code == ErrorCode.INVALID_TRANSITION


# ---------------------------------------------------------------------------
# 3. Авторизация акторов и принадлежность заявки
# ---------------------------------------------------------------------------
def test_client_cannot_execute_system_transition(
    db_session: Session, company: Company, client_user: User, product: Product
):
    app = create_application(db_session, company, client_user, product, status=ApplicationStatus.SUBMITTED)

    with pytest.raises(ApiError) as exc_info:
        transition(
            session=db_session,
            application=app,
            to_status=ApplicationStatus.DATA_CHECK,
            actor_type=ActorType.CLIENT,
            actor_id=client_user.id,
            actor_role=Role.CLIENT.value,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == ErrorCode.INVALID_TRANSITION


def test_system_cannot_execute_client_transition(
    db_session: Session, company: Company, client_user: User, product: Product
):
    app = create_application(db_session, company, client_user, product, status=ApplicationStatus.DRAFT)

    with pytest.raises(ApiError) as exc_info:
        transition(
            session=db_session,
            application=app,
            to_status=ApplicationStatus.SUBMITTED,
            actor_type=ActorType.SYSTEM,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == ErrorCode.INVALID_TRANSITION


def test_other_client_gets_404_not_found(
    db_session: Session, company: Company, client_user: User, other_client: User, product: Product
):
    """Клиент при обращении к чужой заявке получает 404 NOT_FOUND (существование не раскрываем)."""
    app = create_application(db_session, company, client_user, product, status=ApplicationStatus.DRAFT)

    with pytest.raises(ApiError) as exc_info:
        transition(
            session=db_session,
            application=app,
            to_status=ApplicationStatus.SUBMITTED,
            actor_type=ActorType.CLIENT,
            actor_id=other_client.id,
            actor_role=Role.CLIENT.value,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.code == ErrorCode.NOT_FOUND


def test_wrong_role_for_client_actor_raises_403(
    db_session: Session, company: Company, client_user: User, product: Product
):
    app = create_application(db_session, company, client_user, product, status=ApplicationStatus.DRAFT)

    with pytest.raises(ApiError) as exc_info:
        transition(
            session=db_session,
            application=app,
            to_status=ApplicationStatus.SUBMITTED,
            actor_type=ActorType.CLIENT,
            actor_id=client_user.id,
            actor_role=Role.OPERATOR.value,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.code == ErrorCode.FORBIDDEN


def test_wrong_role_for_operator_actor_raises_403(
    db_session: Session, company: Company, client_user: User, operator_user: User, product: Product
):
    app = create_application(
        db_session,
        company,
        client_user,
        product,
        status=ApplicationStatus.MANUAL_REVIEW,
        assigned_operator_id=operator_user.id,
    )

    with pytest.raises(ApiError) as exc_info:
        transition(
            session=db_session,
            application=app,
            to_status=ApplicationStatus.OFFER,
            actor_type=ActorType.OPERATOR,
            actor_id=operator_user.id,
            actor_role=Role.CLIENT.value,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.code == ErrorCode.FORBIDDEN


# ---------------------------------------------------------------------------
# 4. Оптимистичная блокировка (version / If-Match)
# ---------------------------------------------------------------------------
def test_optimistic_locking_success_and_conflict(
    db_session: Session, company: Company, client_user: User, product: Product
):
    app = create_application(db_session, company, client_user, product, status=ApplicationStatus.DRAFT, version=1)

    # 1. Неверная версия -> 409 VERSION_CONFLICT
    with pytest.raises(ApiError) as exc_info:
        transition(
            session=db_session,
            application=app,
            to_status=ApplicationStatus.SUBMITTED,
            actor_type=ActorType.CLIENT,
            actor_id=client_user.id,
            actor_role=Role.CLIENT.value,
            expected_version=999,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == ErrorCode.VERSION_CONFLICT

    # 2. Верная версия -> успех и инкремент версии
    transition(
        session=db_session,
        application=app,
        to_status=ApplicationStatus.SUBMITTED,
        actor_type=ActorType.CLIENT,
        actor_id=client_user.id,
        actor_role=Role.CLIENT.value,
        expected_version=1,
    )
    assert app.version == 2


# ---------------------------------------------------------------------------
# 5. Сквозной сценарий и полный аудит статусов
# ---------------------------------------------------------------------------
def test_end_to_end_happy_path_audit_log(
    db_session: Session, company: Company, client_user: User, operator_user: User, product: Product
):
    """Сквозной путь DRAFT -> SUBMITTED -> DATA_CHECK -> ENRICHMENT -> SCORING -> OFFER -> ACCEPTED -> SIGNING -> DISBURSED.

    Проверяем правильность всех 8 записей истории статусов.
    """
    app = create_application(db_session, company, client_user, product, status=ApplicationStatus.DRAFT)

    # 1. DRAFT -> SUBMITTED
    transition(db_session, app, ApplicationStatus.SUBMITTED, ActorType.CLIENT, client_user.id, Role.CLIENT.value)
    assert app.submitted_at is not None

    # 2. SUBMITTED -> DATA_CHECK
    transition(db_session, app, ApplicationStatus.DATA_CHECK, ActorType.SYSTEM)

    # 3. DATA_CHECK -> ENRICHMENT
    transition(db_session, app, ApplicationStatus.ENRICHMENT, ActorType.SYSTEM)

    # 4. ENRICHMENT -> SCORING
    transition(db_session, app, ApplicationStatus.SCORING, ActorType.SYSTEM)

    # 5. SCORING -> OFFER
    transition(db_session, app, ApplicationStatus.OFFER, ActorType.SYSTEM)

    # 6. OFFER -> ACCEPTED
    transition(db_session, app, ApplicationStatus.ACCEPTED, ActorType.CLIENT, client_user.id, Role.CLIENT.value)

    # 7. ACCEPTED -> SIGNING
    transition(db_session, app, ApplicationStatus.SIGNING, ActorType.SYSTEM)

    # 8. SIGNING -> DISBURSED
    transition(db_session, app, ApplicationStatus.DISBURSED, ActorType.CLIENT, client_user.id, Role.CLIENT.value)

    assert app.status == ApplicationStatus.DISBURSED.value
    assert app.version == 9

    # Проверяем историю
    history_entries = (
        db_session.query(ApplicationStatusHistory)
        .filter_by(application_id=app.id)
        .order_by(ApplicationStatusHistory.created_at.asc())
        .all()
    )
    assert len(history_entries) == 8

    expected_pairs = [
        ("DRAFT", "SUBMITTED", "CLIENT"),
        ("SUBMITTED", "DATA_CHECK", "SYSTEM"),
        ("DATA_CHECK", "ENRICHMENT", "SYSTEM"),
        ("ENRICHMENT", "SCORING", "SYSTEM"),
        ("SCORING", "OFFER", "SYSTEM"),
        ("OFFER", "ACCEPTED", "CLIENT"),
        ("ACCEPTED", "SIGNING", "SYSTEM"),
        ("SIGNING", "DISBURSED", "CLIENT"),
    ]

    for entry, (expected_from, expected_to, expected_actor) in zip(history_entries, expected_pairs, strict=True):
        assert entry.from_status == expected_from
        assert entry.to_status == expected_to
        assert entry.actor_type == expected_actor


# ---------------------------------------------------------------------------
# 6. Логика назначения оператора (take_in_review)
# ---------------------------------------------------------------------------
def test_take_in_review_lifecycle(
    db_session: Session, company: Company, client_user: User, operator_user: User, other_operator: User, product: Product
):
    app = create_application(
        db_session,
        company,
        client_user,
        product,
        status=ApplicationStatus.MANUAL_REVIEW,
        assigned_operator_id=None,
    )

    # 1. Попытка принять решение не назначенным оператором -> 409 CONFLICT
    with pytest.raises(ApiError) as exc_info:
        transition(
            session=db_session,
            application=app,
            to_status=ApplicationStatus.OFFER,
            actor_type=ActorType.OPERATOR,
            actor_id=operator_user.id,
            actor_role=Role.OPERATOR.value,
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == ErrorCode.CONFLICT

    # 2. Неверная роль для take -> 403 FORBIDDEN
    with pytest.raises(ApiError) as exc_info:
        take_in_review(db_session, app, operator_id=client_user.id, operator_role=Role.CLIENT.value)
    assert exc_info.value.status_code == 403
    assert exc_info.value.code == ErrorCode.FORBIDDEN

    # 3. Успешный take оператором 1
    take_in_review(db_session, app, operator_id=operator_user.id, operator_role=Role.OPERATOR.value)
    assert app.assigned_operator_id == operator_user.id
    assert app.status == ApplicationStatus.MANUAL_REVIEW.value
    assert app.version == 2

    # Проверяем запись в истории: reason_code=TAKEN
    take_hist = (
        db_session.query(ApplicationStatusHistory)
        .filter_by(application_id=app.id)
        .order_by(ApplicationStatusHistory.created_at.desc())
        .first()
    )
    assert take_hist.from_status == "MANUAL_REVIEW"
    assert take_hist.to_status == "MANUAL_REVIEW"
    assert take_hist.reason_code == "TAKEN"

    # 4. Попытка взять оператором 2 -> 409 CONFLICT
    with pytest.raises(ApiError) as exc_info:
        take_in_review(db_session, app, operator_id=other_operator.id, operator_role=Role.OPERATOR.value)
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == ErrorCode.CONFLICT

    # 5. Повторный take тем же оператором 1 идемпотентен
    res = take_in_review(db_session, app, operator_id=operator_user.id, operator_role=Role.OPERATOR.value)
    assert res.version == 2

    # 6. Решение другим оператором отклоняется с 409 CONFLICT
    with pytest.raises(ApiError) as exc_info:
        transition(
            session=db_session,
            application=app,
            to_status=ApplicationStatus.OFFER,
            actor_type=ActorType.OPERATOR,
            actor_id=other_operator.id,
            actor_role=Role.OPERATOR.value,
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == ErrorCode.CONFLICT

    # 7. Решение назначенным оператором 1 выполняется успешно
    transition(
        session=db_session,
        application=app,
        to_status=ApplicationStatus.OFFER,
        actor_type=ActorType.OPERATOR,
        actor_id=operator_user.id,
        actor_role=Role.OPERATOR.value,
    )
    assert app.status == ApplicationStatus.OFFER.value


def test_take_in_review_on_non_manual_review_status_raises_409(
    db_session: Session, company: Company, client_user: User, operator_user: User, product: Product
):
    app = create_application(db_session, company, client_user, product, status=ApplicationStatus.DRAFT)

    with pytest.raises(ApiError) as exc_info:
        take_in_review(db_session, app, operator_id=operator_user.id, operator_role=Role.OPERATOR.value)

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == ErrorCode.INVALID_TRANSITION


# ---------------------------------------------------------------------------
# 7. Ограничение раундов уточнений (MAX_INFO_ROUNDS -> MANUAL_REVIEW)
# ---------------------------------------------------------------------------
def test_info_rounds_limit_redirects_to_manual_review(
    db_session: Session, company: Company, client_user: User, product: Product, monkeypatch
):
    """При превышении MAX_INFO_ROUNDS заявка перенаправляется в MANUAL_REVIEW с INFO_ROUNDS_EXCEEDED."""
    from app.config import Settings

    # Устанавливаем max_info_rounds = 2 для предсказуемого теста
    monkeypatch.setattr("app.state_machine.machine.get_settings", lambda: Settings(max_info_rounds=2))

    app = create_application(
        db_session, company, client_user, product, status=ApplicationStatus.DATA_CHECK, info_rounds=0
    )

    # Раунд 1: DATA_CHECK -> NEEDS_INFO
    transition(db_session, app, ApplicationStatus.NEEDS_INFO, ActorType.SYSTEM)
    assert app.status == ApplicationStatus.NEEDS_INFO.value
    assert app.info_rounds == 1

    # Клиент отвечает: NEEDS_INFO -> DATA_CHECK
    transition(db_session, app, ApplicationStatus.DATA_CHECK, ActorType.CLIENT, client_user.id, Role.CLIENT.value)

    # Раунд 2: DATA_CHECK -> NEEDS_INFO
    transition(db_session, app, ApplicationStatus.NEEDS_INFO, ActorType.SYSTEM)
    assert app.status == ApplicationStatus.NEEDS_INFO.value
    assert app.info_rounds == 2

    # Клиент отвечает: NEEDS_INFO -> DATA_CHECK
    transition(db_session, app, ApplicationStatus.DATA_CHECK, ActorType.CLIENT, client_user.id, Role.CLIENT.value)

    # Попытка 3-го раунда (лимит 2 исчерпан): автоматический перевод в MANUAL_REVIEW!
    transition(db_session, app, ApplicationStatus.NEEDS_INFO, ActorType.SYSTEM)
    assert app.status == ApplicationStatus.MANUAL_REVIEW.value
    # info_rounds не увеличивается сверх лимита
    assert app.info_rounds == 2

    # Проверяем запись в истории с кодом INFO_ROUNDS_EXCEEDED
    last_hist = (
        db_session.query(ApplicationStatusHistory)
        .filter_by(application_id=app.id)
        .order_by(ApplicationStatusHistory.created_at.desc())
        .first()
    )
    assert last_hist.to_status == "MANUAL_REVIEW"
    assert last_hist.reason_code == "INFO_ROUNDS_EXCEEDED"


# ---------------------------------------------------------------------------
# 8. Расчёт дедлайнов (expires_at)
# ---------------------------------------------------------------------------
def test_expires_at_calculation(db_session: Session, company: Company, client_user: User, product: Product):
    app = create_application(db_session, company, client_user, product, status=ApplicationStatus.DATA_CHECK)

    # 1. NEEDS_INFO -> expires_at = now + needs_info_ttl_hours
    transition(db_session, app, ApplicationStatus.NEEDS_INFO, ActorType.SYSTEM)
    assert app.expires_at is not None
    assert app.expires_at > datetime.now(timezone.utc)

    # 2. DATA_CHECK -> expires_at = None
    transition(db_session, app, ApplicationStatus.DATA_CHECK, ActorType.CLIENT, client_user.id, Role.CLIENT.value)
    assert app.expires_at is None

    # 3. OFFER с переданным valid_until
    custom_valid_until = datetime.now(timezone.utc) + timedelta(days=5)
    app.status = ApplicationStatus.SCORING.value
    db_session.commit()

    transition(
        session=db_session,
        application=app,
        to_status=ApplicationStatus.OFFER,
        actor_type=ActorType.SYSTEM,
        payload={"valid_until": custom_valid_until.isoformat()},
    )
    assert app.expires_at is not None
    assert abs((app.expires_at - custom_valid_until).total_seconds()) < 5

    # 4. SIGNING -> expires_at = now + signing_ttl_hours
    app.status = ApplicationStatus.ACCEPTED.value
    db_session.commit()

    transition(db_session, app, ApplicationStatus.SIGNING, ActorType.SYSTEM)
    assert app.expires_at is not None

    # 5. DISBURSED -> expires_at = None
    transition(db_session, app, ApplicationStatus.DISBURSED, ActorType.CLIENT, client_user.id, Role.CLIENT.value)
    assert app.expires_at is None


# ---------------------------------------------------------------------------
# 9. Синхронизация статусов офферов
# ---------------------------------------------------------------------------
def test_offer_state_synchronization(db_session: Session, company: Company, client_user: User, product: Product):
    app = create_application(db_session, company, client_user, product, status=ApplicationStatus.OFFER)

    # Создаём активный оффер
    offer = Offer(
        application_id=app.id,
        kind="ORIGINAL",
        amount_rub=1_000_000,
        term_months=12,
        rate_percent=18.0,
        monthly_payment_rub=91_680,
        valid_until=datetime.now(timezone.utc) + timedelta(days=3),
        state=OfferState.ACTIVE.value,
    )
    db_session.add(offer)
    db_session.commit()

    # Принятие оффера клиентом -> offer.state = ACCEPTED
    transition(db_session, app, ApplicationStatus.ACCEPTED, ActorType.CLIENT, client_user.id, Role.CLIENT.value)
    db_session.refresh(offer)
    assert offer.state == OfferState.ACCEPTED.value

    # Тестируем отказ (отмену) на новой заявке с оффером
    app2 = create_application(db_session, company, client_user, product, status=ApplicationStatus.OFFER)
    offer2 = Offer(
        application_id=app2.id,
        kind="ORIGINAL",
        amount_rub=500_000,
        term_months=12,
        rate_percent=18.0,
        monthly_payment_rub=45_000,
        valid_until=datetime.now(timezone.utc) + timedelta(days=3),
        state=OfferState.ACTIVE.value,
    )
    db_session.add(offer2)
    db_session.commit()

    transition(db_session, app2, ApplicationStatus.CANCELLED, ActorType.CLIENT, client_user.id, Role.CLIENT.value)
    db_session.refresh(offer2)
    assert offer2.state == OfferState.DECLINED.value


# ---------------------------------------------------------------------------
# 10. Постановка задач в очередь jobs
# ---------------------------------------------------------------------------
def test_jobs_enqueued_on_transitions(db_session: Session, company: Company, client_user: User, product: Product):
    app = create_application(db_session, company, client_user, product, status=ApplicationStatus.DRAFT)

    # 1. DRAFT -> SUBMITTED ставит data_check
    transition(db_session, app, ApplicationStatus.SUBMITTED, ActorType.CLIENT, client_user.id, Role.CLIENT.value)

    job = db_session.query(Job).filter_by(application_id=app.id, type="data_check").first()
    assert job is not None
    assert job.step_key == str(app.version)
    assert job.state == "PENDING"

    # 2. DATA_CHECK -> ENRICHMENT ставит enrichment
    app.status = ApplicationStatus.DATA_CHECK.value
    db_session.commit()

    transition(db_session, app, ApplicationStatus.ENRICHMENT, ActorType.SYSTEM)
    job_enrich = db_session.query(Job).filter_by(application_id=app.id, type="enrichment").first()
    assert job_enrich is not None

    # 3. ENRICHMENT -> SCORING ставит scoring_decision
    transition(db_session, app, ApplicationStatus.SCORING, ActorType.SYSTEM)
    job_scoring = db_session.query(Job).filter_by(application_id=app.id, type="scoring_decision").first()
    assert job_scoring is not None

    # 4. OFFER -> ACCEPTED ставит prepare_documents
    app.status = ApplicationStatus.OFFER.value
    db_session.commit()

    transition(db_session, app, ApplicationStatus.ACCEPTED, ActorType.CLIENT, client_user.id, Role.CLIENT.value)
    job_prep = db_session.query(Job).filter_by(application_id=app.id, type="prepare_documents").first()
    assert job_prep is not None


# ---------------------------------------------------------------------------
# 11. Идемпотентность воркера (SYSTEM)
# ---------------------------------------------------------------------------
def test_system_idempotency_skip(db_session: Session, company: Company, client_user: User, product: Product):
    """Повторный переход воркером в тот же статус не вызывает ошибки и не делает дубликатов."""
    app = create_application(db_session, company, client_user, product, status=ApplicationStatus.ENRICHMENT, version=5)

    res = transition(
        session=db_session,
        application=app,
        to_status=ApplicationStatus.ENRICHMENT,
        actor_type=ActorType.SYSTEM,
        idempotent=True,
    )

    assert res.version == 5
    assert res.status == ApplicationStatus.ENRICHMENT.value

    # Историю не дублировали
    history_count = db_session.query(ApplicationStatusHistory).filter_by(application_id=app.id).count()
    assert history_count == 0


# ---------------------------------------------------------------------------
# 12. get_allowed_transitions
# ---------------------------------------------------------------------------
def test_get_allowed_transitions(
    db_session: Session, company: Company, client_user: User, other_client: User, operator_user: User, product: Product
):
    app = create_application(db_session, company, client_user, product, status=ApplicationStatus.DRAFT)

    # Для владельца черновика доступны SUBMITTED и CANCELLED
    allowed = get_allowed_transitions(app, ActorType.CLIENT, client_user.id)
    assert set(allowed) == {ApplicationStatus.SUBMITTED, ApplicationStatus.CANCELLED}

    # Для чужого клиента список пуст
    assert get_allowed_transitions(app, ActorType.CLIENT, other_client.id) == []

    # Для оператора на DRAFT список пуст
    assert get_allowed_transitions(app, ActorType.OPERATOR, operator_user.id) == []

    # На MANUAL_REVIEW до назначения список оператора пуст
    app.status = ApplicationStatus.MANUAL_REVIEW.value
    assert get_allowed_transitions(app, ActorType.OPERATOR, operator_user.id) == []

    # После назначения оператору доступны OFFER, COUNTER_OFFER, NEEDS_INFO, REJECTED
    app.assigned_operator_id = operator_user.id
    allowed_op = get_allowed_transitions(app, ActorType.OPERATOR, operator_user.id)
    assert set(allowed_op) == {
        ApplicationStatus.OFFER,
        ApplicationStatus.COUNTER_OFFER,
        ApplicationStatus.NEEDS_INFO,
        ApplicationStatus.REJECTED,
    }

    # В финальном статусе переходов нет
    app.status = ApplicationStatus.DISBURSED.value
    assert get_allowed_transitions(app, ActorType.CLIENT, client_user.id) == []
    assert get_allowed_transitions(app, ActorType.OPERATOR, operator_user.id) == []
    assert get_allowed_transitions(app, ActorType.SYSTEM) == []


# ---------------------------------------------------------------------------
# 13. Тесты на замечания ревью (Review Findings)
# ---------------------------------------------------------------------------
def test_system_idempotency_invalid_target_and_version_conflict(
    db_session: Session, company: Company, client_user: User, product: Product
):
    """Идемпотентность воркера не должна пропускать невалидные системные статусы (DRAFT) или конфликты версий."""
    app = create_application(db_session, company, client_user, product, status=ApplicationStatus.DRAFT, version=1)

    # 1. Системный вызов DRAFT -> DRAFT не должен молча проходить
    with pytest.raises(ApiError) as exc_info:
        transition(
            session=db_session,
            application=app,
            to_status=ApplicationStatus.DRAFT,
            actor_type=ActorType.SYSTEM,
            idempotent=True,
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == ErrorCode.INVALID_TRANSITION

    # 2. Повтор с устаревшей версией даёт 409 VERSION_CONFLICT
    app.status = ApplicationStatus.ENRICHMENT.value
    app.version = 3
    db_session.commit()

    with pytest.raises(ApiError) as exc_info:
        transition(
            session=db_session,
            application=app,
            to_status=ApplicationStatus.ENRICHMENT,
            actor_type=ActorType.SYSTEM,
            expected_version=1,
            idempotent=True,
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == ErrorCode.VERSION_CONFLICT

    # 3. Системный вызов MANUAL_REVIEW -> MANUAL_REVIEW обязан отклоняться с 409
    app.status = ApplicationStatus.MANUAL_REVIEW.value
    app.version = 4
    db_session.commit()

    with pytest.raises(ApiError) as exc_info:
        transition(
            session=db_session,
            application=app,
            to_status=ApplicationStatus.MANUAL_REVIEW,
            actor_type=ActorType.SYSTEM,
            idempotent=True,
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == ErrorCode.INVALID_TRANSITION


def test_take_in_review_repeated_with_outdated_version_raises_409(
    db_session: Session, company: Company, client_user: User, operator_user: User, product: Product
):
    """Повторный take_in_review тем же оператором с устаревшим If-Match должен давать 409 VERSION_CONFLICT."""
    app = create_application(
        db_session, company, client_user, product, status=ApplicationStatus.MANUAL_REVIEW, version=1
    )

    # Первый take -> version становится 2
    take_in_review(db_session, app, operator_id=operator_user.id, operator_role=Role.OPERATOR.value, expected_version=1)
    assert app.version == 2
    assert app.assigned_operator_id == operator_user.id

    # Повторный take с устаревшим If-Match (expected_version=1) обязан выбросить 409 VERSION_CONFLICT
    with pytest.raises(ApiError) as exc_info:
        take_in_review(
            db_session,
            app,
            operator_id=operator_user.id,
            operator_role=Role.OPERATOR.value,
            expected_version=1,
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == ErrorCode.VERSION_CONFLICT

    # Повторный take с актуальным If-Match (expected_version=2) успешен
    res = take_in_review(
        db_session,
        app,
        operator_id=operator_user.id,
        operator_role=Role.OPERATOR.value,
        expected_version=2,
    )
    assert res.version == 2


def test_get_allowed_transitions_respects_actor_role(
    db_session: Session, company: Company, client_user: User, operator_user: User, product: Product
):
    """get_allowed_transitions должен валидировать actor_role и не возвращать действия не своей роли."""
    app = create_application(
        db_session,
        company,
        client_user,
        product,
        status=ApplicationStatus.MANUAL_REVIEW,
        assigned_operator_id=operator_user.id,
    )

    # 1. Попытка запросить действия оператора с ролью CLIENT -> пустой список
    res_client_role = get_allowed_transitions(
        app,
        actor_type=ActorType.OPERATOR,
        actor_id=operator_user.id,
        actor_role=Role.CLIENT.value,
    )
    assert res_client_role == []

    # 2. Запрос с корректной ролью OPERATOR -> список действий
    res_operator_role = get_allowed_transitions(
        app,
        actor_type=ActorType.OPERATOR,
        actor_id=operator_user.id,
        actor_role=Role.OPERATOR.value,
    )
    assert set(res_operator_role) == {
        ApplicationStatus.OFFER,
        ApplicationStatus.COUNTER_OFFER,
        ApplicationStatus.NEEDS_INFO,
        ApplicationStatus.REJECTED,
    }

    # 3. Черновик: клиент с ролью OPERATOR не может совершать клиентские действия
    app.status = ApplicationStatus.DRAFT.value
    res_wrong_client = get_allowed_transitions(
        app,
        actor_type=ActorType.CLIENT,
        actor_id=client_user.id,
        actor_role=Role.OPERATOR.value,
    )
    assert res_wrong_client == []

    # 4. Черновик: клиент с ролью CLIENT получает свои переходы
    res_correct_client = get_allowed_transitions(
        app,
        actor_type=ActorType.CLIENT,
        actor_id=client_user.id,
        actor_role=Role.CLIENT.value,
    )
    assert set(res_correct_client) == {ApplicationStatus.SUBMITTED, ApplicationStatus.CANCELLED}

