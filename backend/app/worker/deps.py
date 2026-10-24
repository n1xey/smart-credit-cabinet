"""Внедрение зависимостей для воркера конвейера."""
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import uuid

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_sessionmaker
from app.services.bki_port import BkiClientProtocol
from app.services.egrul_port import EgrulClientProtocol, get_egrul_client
from app.services.scoring_port import DecisionProtocol, ScoringProtocol


@dataclass
class WorkerDeps:
    """Контейнер зависимостей воркера кредитного конвейера."""

    session_factory: Callable[[], Session]
    scoring_service: ScoringProtocol
    decision_service: DecisionProtocol
    bki_client: BkiClientProtocol
    egrul_client: EgrulClientProtocol
    uploads_dir: Path
    settings: Settings


def get_worker_deps(
    session_factory: Callable[[], Session] | None = None,
    scoring_service: ScoringProtocol | None = None,
    decision_service: DecisionProtocol | None = None,
    bki_client: BkiClientProtocol | None = None,
    egrul_client: EgrulClientProtocol | None = None,
    uploads_dir: Path | None = None,
    settings: Settings | None = None,
) -> WorkerDeps:
    """Фабрика создания зависимостей воркера.

    В проде (когда сервисы не переданы явно) пытается подключить реальные модули Участника 4.
    Если модули Участника 4 ещё не выкачены, выбрасывает понятный RuntimeError при старте воркера.
    В тестах зависимости передаются явно (Fake / Stub реализации).
    """
    effective_settings = settings or get_settings()
    effective_session_factory = session_factory or get_sessionmaker()
    effective_uploads_dir = uploads_dir or effective_settings.uploads_dir
    effective_egrul = egrul_client or get_egrul_client()

    effective_scoring = scoring_service
    effective_decision = decision_service
    effective_bki = bki_client

    if effective_scoring is None or effective_decision is None or effective_bki is None:
        try:
            from app.integrations.bki import BkiClient  # type: ignore[import-not-found]
            from app.scoring.engine import DecisionService, ScoringService  # type: ignore[import-not-found]

            effective_scoring = effective_scoring or ScoringService()
            effective_decision = effective_decision or DecisionService()
            effective_bki = effective_bki or BkiClient()
        except ImportError as e:
            raise RuntimeError(
                "Реальные сервисы скоринга, решений или БКИ Участника 4 ещё не подключены в репозитории. "
                "Для запуска воркера передайте тестовые зависимости (WorkerDeps с fakes) или дождитесь релиза Участника 4."
            ) from e

    return WorkerDeps(
        session_factory=effective_session_factory,
        scoring_service=effective_scoring,
        decision_service=effective_decision,
        bki_client=effective_bki,
        egrul_client=effective_egrul,
        uploads_dir=effective_uploads_dir,
        settings=effective_settings,
    )
