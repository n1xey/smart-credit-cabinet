"""Автомат состояний кредитного конвейера (docs/STATE_MACHINE.md).

Владелец модуля: Участник 2.
Единственная точка входа для смены статусов заявок: state_machine.transition(...).
"""
from app.state_machine.jobs import enqueue_job
from app.state_machine.machine import (
    get_allowed_transitions,
    take_in_review,
    transition,
)
from app.state_machine.transitions import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATUSES,
    TransitionRule,
)

__all__ = [
    "transition",
    "take_in_review",
    "get_allowed_transitions",
    "enqueue_job",
    "ALLOWED_TRANSITIONS",
    "TERMINAL_STATUSES",
    "TransitionRule",
]
