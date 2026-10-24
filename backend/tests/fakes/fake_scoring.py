"""Тестовые реализации (Fake) портов скоринга, принятия решений, БКИ и ЕГРЮЛ."""
from datetime import datetime, timedelta, timezone
from typing import Any

from app.api.schemas.company import CompanyInput
from app.enums import LegalForm
from app.services.bki_port import BkiReport, SourceUnavailableError
from app.services.scoring_port import (
    DecisionOffer,
    DecisionOutput,
    FactorLine,
    ScoringInputs,
    ScoringResult,
)


class FakeScoringService:
    """Тестовая реализация сервиса скоринга."""

    def __init__(
        self,
        score: int = 750,
        grade: str = "A",
        factors: list[FactorLine] | None = None,
        knockouts: list[str] | None = None,
        model_version: str = "1.0.0",
        exception_to_raise: Exception | None = None,
    ) -> None:
        self.score = score
        self.grade = grade
        self.factors = factors or [
            FactorLine(factor="revenue_stability", impact="+", weight=0.3, value="high"),
            FactorLine(factor="debt_burden", impact="neutral", weight=0.2, value="medium"),
        ]
        self.knockouts = knockouts or []
        self.model_version = model_version
        self.exception_to_raise = exception_to_raise
        self.calls: list[ScoringInputs] = []

    def calculate_score(self, inputs: ScoringInputs) -> ScoringResult:
        if self.exception_to_raise:
            raise self.exception_to_raise
        self.calls.append(inputs)
        return ScoringResult(
            score=self.score,
            grade=self.grade,
            factors=self.factors,
            knockouts=self.knockouts,
            model_version=self.model_version,
        )


class FakeDecisionService:
    """Тестовая реализация сервиса принятия кредитных решений."""

    def __init__(
        self,
        outcome: str = "OFFER",
        decided_by: str = "AUTO",
        reason_codes: list[str] | None = None,
        comment: str | None = None,
        offer: DecisionOffer | None = None,
        info_request_items: list[str] | None = None,
        exception_to_raise: Exception | None = None,
    ) -> None:
        self.outcome = outcome
        self.decided_by = decided_by
        self.reason_codes = reason_codes or []
        self.comment = comment
        self.offer = offer
        self.info_request_items = info_request_items
        self.exception_to_raise = exception_to_raise
        self.calls: list[tuple[ScoringInputs, ScoringResult]] = []

    def make_decision(self, inputs: ScoringInputs, scoring_result: ScoringResult) -> DecisionOutput:
        if self.exception_to_raise:
            raise self.exception_to_raise
        self.calls.append((inputs, scoring_result))

        offer = self.offer
        if offer is None and self.outcome in ("OFFER", "COUNTER_OFFER"):
            valid_until = datetime.now(timezone.utc) + timedelta(days=3)
            amount = inputs.requested_amount_rub or 1_000_000
            term = inputs.requested_term_months or 12
            rate = 15.0
            monthly = int((amount * (1 + rate / 100)) / term)
            offer = DecisionOffer(
                kind="ORIGINAL" if self.outcome == "OFFER" else "COUNTER",
                amount_rub=amount,
                term_months=term,
                rate_percent=rate,
                monthly_payment_rub=monthly,
                valid_until=valid_until,
                explanation="Одобрено на запрошенных условиях" if self.outcome == "OFFER" else "Предложены скорректированные условия",
            )

        return DecisionOutput(
            outcome=self.outcome,
            decided_by=self.decided_by,
            reason_codes=self.reason_codes,
            comment=self.comment,
            offer=offer,
            info_request_items=self.info_request_items,
        )


class FakeBkiClient:
    """Тестовая реализация клиента БКИ."""

    def __init__(
        self,
        reports: dict[str, BkiReport] | None = None,
        unreachable_inns: set[str] | None = None,
        raise_unreachable: bool = False,
    ) -> None:
        self.reports = reports or {}
        self.unreachable_inns = unreachable_inns or set()
        self.raise_unreachable = raise_unreachable
        self.calls: list[str] = []

    def get_report(self, inn: str) -> BkiReport:
        self.calls.append(inn)
        if self.raise_unreachable or inn in self.unreachable_inns:
            raise SourceUnavailableError(f"BKI service unreachable for INN {inn}")
        if inn in self.reports:
            return self.reports[inn]
        return BkiReport(
            inn=inn,
            rating=700,
            active_credits_count=1,
            overdue_amount_rub=0,
            raw_payload={"status": "OK", "rating": 700},
        )


class FakeEgrulClient:
    """Тестовая реализация клиента ЕГРЮЛ."""

    def __init__(
        self,
        registry: dict[str, CompanyInput] | None = None,
        unreachable_inns: set[str] | None = None,
        raise_unreachable: bool = False,
    ) -> None:
        self.registry = registry or {}
        self.unreachable_inns = unreachable_inns or set()
        self.raise_unreachable = raise_unreachable
        self.calls: list[str] = []

    def lookup(self, inn: str) -> CompanyInput | None:
        self.calls.append(inn)
        if self.raise_unreachable or inn in self.unreachable_inns:
            raise SourceUnavailableError(f"EGRUL service unreachable for INN {inn}")
        if inn in self.registry:
            return self.registry[inn]
        return CompanyInput(
            inn=inn,
            name='ООО "Ромашка"',
            legal_form=LegalForm.OOO,
            registration_date="2020-01-15",
            okved="62.01",
            address="г. Москва, ул. Ленина, д. 1",
        )
