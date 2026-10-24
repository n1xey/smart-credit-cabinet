"""Обработчики шагов конвейера воркера.

Каждый обработчик имеет сигнатуру:
    handler(session: Session, job: Job, deps: WorkerDeps) -> None
"""
from app.worker.handlers.data_check import handle_data_check
from app.worker.handlers.enrichment import handle_enrichment
from app.worker.handlers.prepare_documents import handle_prepare_documents
from app.worker.handlers.scoring import handle_scoring_decision

HANDLERS = {
    "data_check": handle_data_check,
    "enrichment": handle_enrichment,
    "scoring_decision": handle_scoring_decision,
    "prepare_documents": handle_prepare_documents,
}

__all__ = [
    "handle_data_check",
    "handle_enrichment",
    "handle_scoring_decision",
    "handle_prepare_documents",
    "HANDLERS",
]
