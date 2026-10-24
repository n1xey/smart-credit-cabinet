"""Правила и граф переходов автомата состояний (docs/STATE_MACHINE.md).

Любой переход в системе обязан строго соответствовать этому графу.
"""
from dataclasses import dataclass

from app.enums import ActorType, ApplicationStatus


@dataclass(frozen=True)
class TransitionRule:
    from_status: ApplicationStatus
    to_status: ApplicationStatus
    allowed_actors: frozenset[ActorType]
    description: str


# Терминальные статусы: из них переходов нет.
TERMINAL_STATUSES: frozenset[ApplicationStatus] = frozenset(
    {
        ApplicationStatus.REJECTED,
        ApplicationStatus.CANCELLED,
        ApplicationStatus.EXPIRED,
        ApplicationStatus.DISBURSED,
    }
)

# Статусы, для которых допустим повтор системного шага воркером (SYSTEM).
# MANUAL_REVIEW исключён: self-transition отсутствует, повторяемых фоновых задач воркера в этом статусе нет.
# Финальные статусы (REJECTED, EXPIRED) блокируются проверкой терминальных статусов.
SYSTEM_TARGET_STATUSES: frozenset[ApplicationStatus] = frozenset(
    {
        ApplicationStatus.DATA_CHECK,
        ApplicationStatus.NEEDS_INFO,
        ApplicationStatus.ENRICHMENT,
        ApplicationStatus.SCORING,
        ApplicationStatus.OFFER,
        ApplicationStatus.COUNTER_OFFER,
        ApplicationStatus.SIGNING,
    }
)

# Полный список допустимых переходов согласно docs/STATE_MACHINE.md
ALLOWED_TRANSITIONS: list[TransitionRule] = [
    # DRAFT
    TransitionRule(
        ApplicationStatus.DRAFT,
        ApplicationStatus.SUBMITTED,
        frozenset({ActorType.CLIENT}),
        "Клиент подаёт заявку на рассмотрение",
    ),
    TransitionRule(
        ApplicationStatus.DRAFT,
        ApplicationStatus.CANCELLED,
        frozenset({ActorType.CLIENT}),
        "Клиент отменяет черновик заявки",
    ),
    # SUBMITTED
    TransitionRule(
        ApplicationStatus.SUBMITTED,
        ApplicationStatus.DATA_CHECK,
        frozenset({ActorType.SYSTEM}),
        "Система начинает проверку полноты и корректности данных",
    ),
    # DATA_CHECK
    TransitionRule(
        ApplicationStatus.DATA_CHECK,
        ApplicationStatus.NEEDS_INFO,
        frozenset({ActorType.SYSTEM}),
        "Система запрашивает недостающие данные или документы",
    ),
    TransitionRule(
        ApplicationStatus.DATA_CHECK,
        ApplicationStatus.ENRICHMENT,
        frozenset({ActorType.SYSTEM}),
        "Данные полны и корректны, переход к обогащению из БКИ/ЕГРЮЛ",
    ),
    TransitionRule(
        ApplicationStatus.DATA_CHECK,
        ApplicationStatus.REJECTED,
        frozenset({ActorType.SYSTEM}),
        "Выявлен стоп-фактор первичной проверки (например, невалидный ИНН)",
    ),
    TransitionRule(
        ApplicationStatus.DATA_CHECK,
        ApplicationStatus.MANUAL_REVIEW,
        frozenset({ActorType.SYSTEM}),
        "Лимит раундов уточнений исчерпан (INFO_ROUNDS_EXCEEDED), передача оператору",
    ),
    # NEEDS_INFO
    TransitionRule(
        ApplicationStatus.NEEDS_INFO,
        ApplicationStatus.DATA_CHECK,
        frozenset({ActorType.CLIENT}),
        "Клиент предоставил запрошенные данные/документы",
    ),
    TransitionRule(
        ApplicationStatus.NEEDS_INFO,
        ApplicationStatus.EXPIRED,
        frozenset({ActorType.SYSTEM}),
        "Срок ожидания ответа на запрос уточнений истёк",
    ),
    TransitionRule(
        ApplicationStatus.NEEDS_INFO,
        ApplicationStatus.CANCELLED,
        frozenset({ActorType.CLIENT}),
        "Клиент отменил заявку на этапе ожидания уточнений",
    ),
    # ENRICHMENT
    TransitionRule(
        ApplicationStatus.ENRICHMENT,
        ApplicationStatus.SCORING,
        frozenset({ActorType.SYSTEM}),
        "Данные из БКИ и ЕГРЮЛ успешно получены, переход к скорингу",
    ),
    TransitionRule(
        ApplicationStatus.ENRICHMENT,
        ApplicationStatus.MANUAL_REVIEW,
        frozenset({ActorType.SYSTEM}),
        "Внешний источник недоступен после повторов, передача оператору",
    ),
    # SCORING
    TransitionRule(
        ApplicationStatus.SCORING,
        ApplicationStatus.OFFER,
        frozenset({ActorType.SYSTEM}),
        "Автоодобрение на запрошенных клиентом условиях",
    ),
    TransitionRule(
        ApplicationStatus.SCORING,
        ApplicationStatus.COUNTER_OFFER,
        frozenset({ActorType.SYSTEM}),
        "Одобрение на альтернативных условиях (контр-предложение)",
    ),
    TransitionRule(
        ApplicationStatus.SCORING,
        ApplicationStatus.MANUAL_REVIEW,
        frozenset({ActorType.SYSTEM}),
        "Требуется ручная проверка заявки кредитным специалистом",
    ),
    TransitionRule(
        ApplicationStatus.SCORING,
        ApplicationStatus.NEEDS_INFO,
        frozenset({ActorType.SYSTEM}),
        "Требуются уточнения данных (например, расхождения с реестром)",
    ),
    TransitionRule(
        ApplicationStatus.SCORING,
        ApplicationStatus.REJECTED,
        frozenset({ActorType.SYSTEM}),
        "Отказ по скорингу или стоп-факторам",
    ),
    # MANUAL_REVIEW
    TransitionRule(
        ApplicationStatus.MANUAL_REVIEW,
        ApplicationStatus.OFFER,
        frozenset({ActorType.OPERATOR}),
        "Оператор одобрил заявку на запрошенных условиях",
    ),
    TransitionRule(
        ApplicationStatus.MANUAL_REVIEW,
        ApplicationStatus.COUNTER_OFFER,
        frozenset({ActorType.OPERATOR}),
        "Оператор сформировал контр-предложение",
    ),
    TransitionRule(
        ApplicationStatus.MANUAL_REVIEW,
        ApplicationStatus.NEEDS_INFO,
        frozenset({ActorType.OPERATOR}),
        "Оператор запросил уточнения у клиента",
    ),
    TransitionRule(
        ApplicationStatus.MANUAL_REVIEW,
        ApplicationStatus.REJECTED,
        frozenset({ActorType.OPERATOR}),
        "Оператор отклонил заявку",
    ),
    # OFFER
    TransitionRule(
        ApplicationStatus.OFFER,
        ApplicationStatus.ACCEPTED,
        frozenset({ActorType.CLIENT}),
        "Клиент принял предложение",
    ),
    TransitionRule(
        ApplicationStatus.OFFER,
        ApplicationStatus.CANCELLED,
        frozenset({ActorType.CLIENT}),
        "Клиент отклонил предложение",
    ),
    TransitionRule(
        ApplicationStatus.OFFER,
        ApplicationStatus.EXPIRED,
        frozenset({ActorType.SYSTEM}),
        "Срок действия предложения истёк",
    ),
    # COUNTER_OFFER
    TransitionRule(
        ApplicationStatus.COUNTER_OFFER,
        ApplicationStatus.ACCEPTED,
        frozenset({ActorType.CLIENT}),
        "Клиент принял контр-предложение",
    ),
    TransitionRule(
        ApplicationStatus.COUNTER_OFFER,
        ApplicationStatus.CANCELLED,
        frozenset({ActorType.CLIENT}),
        "Клиент отклонил контр-предложение",
    ),
    TransitionRule(
        ApplicationStatus.COUNTER_OFFER,
        ApplicationStatus.EXPIRED,
        frozenset({ActorType.SYSTEM}),
        "Срок действия контр-предложения истёк",
    ),
    # ACCEPTED
    TransitionRule(
        ApplicationStatus.ACCEPTED,
        ApplicationStatus.SIGNING,
        frozenset({ActorType.SYSTEM}),
        "Система сформировала пакет документов на подписание",
    ),
    TransitionRule(
        ApplicationStatus.ACCEPTED,
        ApplicationStatus.MANUAL_REVIEW,
        frozenset({ActorType.SYSTEM}),
        "Сбой формирования документов, передача оператору",
    ),

    # SIGNING
    TransitionRule(
        ApplicationStatus.SIGNING,
        ApplicationStatus.DISBURSED,
        frozenset({ActorType.CLIENT}),
        "Клиент подтвердил подписание документов (имитация выдачи)",
    ),
    TransitionRule(
        ApplicationStatus.SIGNING,
        ApplicationStatus.EXPIRED,
        frozenset({ActorType.SYSTEM}),
        "Срок подписания документов истёк",
    ),
]

# Быстрый индекс переходов: (from_status, to_status) -> TransitionRule
_TRANSITION_MAP: dict[tuple[ApplicationStatus, ApplicationStatus], TransitionRule] = {
    (rule.from_status, rule.to_status): rule for rule in ALLOWED_TRANSITIONS
}


def get_transition_rule(
    from_status: ApplicationStatus,
    to_status: ApplicationStatus,
) -> TransitionRule | None:
    """Возвращает правило перехода или None, если переход не разрешён графом."""
    return _TRANSITION_MAP.get((from_status, to_status))


def get_allowed_targets(
    from_status: ApplicationStatus,
    actor_type: ActorType | None = None,
) -> list[ApplicationStatus]:
    """Возвращает список возможных целевых статусов из from_status (опционально фильтруя по актору)."""
    return [
        rule.to_status
        for rule in ALLOWED_TRANSITIONS
        if rule.from_status == from_status and (actor_type is None or actor_type in rule.allowed_actors)
    ]
