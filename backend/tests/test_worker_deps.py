"""Тесты внедрения зависимостей воркера (deps.py) и контрактов портов."""
from datetime import datetime, timezone
import pytest

from app.services.bki_port import BkiClientProtocol, BkiReport, SourceUnavailableError
from app.services.scoring_port import (
    DecisionOffer,
    DecisionOutput,
    DecisionProtocol,
    FactorLine,
    ScoringInputs,
    ScoringProtocol,
    ScoringResult,
)
from app.worker.deps import WorkerDeps, get_worker_deps
from tests.fakes.fake_scoring import (
    FakeBkiClient,
    FakeDecisionService,
    FakeEgrulClient,
    FakeScoringService,
)


def test_worker_deps_with_fakes():
    scoring = FakeScoringService()
    decision = FakeDecisionService()
    bki = FakeBkiClient()
    egrul = FakeEgrulClient()

    deps = get_worker_deps(
        scoring_service=scoring,
        decision_service=decision,
        bki_client=bki,
        egrul_client=egrul,
    )

    assert isinstance(deps, WorkerDeps)
    assert deps.scoring_service is scoring
    assert deps.decision_service is decision
    assert deps.bki_client is bki
    assert deps.egrul_client is egrul
    assert deps.session_factory is not None


def test_worker_deps_raises_when_real_services_missing():
    """Без передачи fakes фабрика пытается найти реальные модули Участника 4 и падает с понятным RuntimeError."""
    with pytest.raises(RuntimeError, match="Реальные сервисы скоринга, решений или БКИ Участника 4 ещё не подключены"):
        get_worker_deps()


def test_fake_protocols_conformance():
    """Проверяем, что Fake-классы реализуют объявленные Protocol-интерфейсы."""
    scoring: ScoringProtocol = FakeScoringService()
    decision: DecisionProtocol = FakeDecisionService()
    bki: BkiClientProtocol = FakeBkiClient()

    inputs = ScoringInputs(
        application_id="app-1",
        inn="7707083893",
        revenue_12m_rub=10_000_000,
        net_profit_12m_rub=1_000_000,
        existing_monthly_payments_rub=50_000,
        requested_amount_rub=1_000_000,
        requested_term_months=12,
        product_code="WORKING_CAPITAL",
    )

    result = scoring.calculate_score(inputs)
    assert isinstance(result, ScoringResult)
    assert result.score == 750
    assert result.grade == "A"

    dec_output = decision.make_decision(inputs, result)
    assert isinstance(dec_output, DecisionOutput)
    assert dec_output.outcome == "OFFER"
    assert dec_output.offer is not None
    assert dec_output.offer.monthly_payment_rub > 0

    report = bki.get_report("7707083893")
    assert isinstance(report, BkiReport)
    assert report.inn == "7707083893"
