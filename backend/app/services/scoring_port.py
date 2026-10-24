"""Порты и контракты данных скоринга и принятия решений.

Владелец модуля: Участник 4 (Scoring & Decision Engine).
Участник 2 объявляет строго контракты (DTO и Protocol) для изоляции воркера
от разрабатываемой логики скоринга.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class ScoringInputs:
    """Входные данные для расчёта скоринга."""

    application_id: str
    inn: str
    revenue_12m_rub: int | None
    net_profit_12m_rub: int | None
    existing_monthly_payments_rub: int | None
    requested_amount_rub: int | None
    requested_term_months: int | None
    product_code: str
    company_name: str | None = None
    legal_form: str | None = None
    bki_report: dict[str, Any] | None = None
    egrul_data: dict[str, Any] | None = None


@dataclass(frozen=True)
class FactorLine:
    """Влияние отдельного фактора на скоринговый балл."""

    factor: str
    impact: str  # "+", "-", "neutral"
    weight: float | None = None
    value: str | None = None


@dataclass(frozen=True)
class ScoringResult:
    """Результат расчёта скорингового балла."""

    score: int
    grade: str
    factors: list[FactorLine]
    knockouts: list[str] = field(default_factory=list)
    model_version: str = "1.0.0"


@dataclass(frozen=True)
class DecisionOffer:
    """Параметры кредитного предложения (оффера)."""

    kind: str  # "ORIGINAL" | "COUNTER"
    amount_rub: int
    term_months: int
    rate_percent: float
    monthly_payment_rub: int
    valid_until: datetime
    explanation: str | None = None


@dataclass(frozen=True)
class DecisionOutput:
    """Итоговое решение скорингового конвейера."""

    outcome: str  # "OFFER" | "COUNTER_OFFER" | "MANUAL_REVIEW" | "NEEDS_INFO" | "REJECTED"
    decided_by: str = "AUTO"
    decided_by_id: str | None = None
    reason_codes: list[str] = field(default_factory=list)
    comment: str | None = None
    offer: DecisionOffer | None = None
    info_request_items: list[str] | None = None


class ScoringProtocol(Protocol):
    """Протокол вычисления скорингового балла."""

    def calculate_score(self, inputs: ScoringInputs) -> ScoringResult:
        """Вычисляет скоринговый балл, грейд и факторы на основе входных данных."""
        ...


class DecisionProtocol(Protocol):
    """Протокол принятия кредитного решения."""

    def make_decision(self, inputs: ScoringInputs, scoring_result: ScoringResult) -> DecisionOutput:
        """Формирует кредитное решение (оффер, контр-оффер, ручной разбор, отказ)."""
        ...
