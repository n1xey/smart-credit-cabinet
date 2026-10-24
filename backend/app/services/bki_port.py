"""Интерфейс-порт и структуры данных для интеграции с БКИ (Бюро кредитных историй).

Владелец интеграции: Участник 4.
Участник 2 объявляет Protocol для вызова внешнего сервиса воркером конвейера.
"""
from dataclasses import dataclass
from typing import Any, Protocol


class SourceUnavailableError(Exception):
    """Внешний источник данных (БКИ, ЕГРЮЛ) недоступен или вернул 5xx ошибку."""

    pass


@dataclass(frozen=True)
class BkiReport:
    """Данные отчёта БКИ по юридическому лицу / ИП (GET /reports/{inn})."""

    inn: str
    rating: int | None = None
    active_credits_count: int = 0
    overdue_amount_rub: int = 0
    raw_payload: dict[str, Any] | None = None


class BkiClientProtocol(Protocol):
    """Протокол взаимодействия с сервисом БКИ."""

    def get_report(self, inn: str) -> BkiReport:
        """Получает кредитный отчёт по ИНН.

        При сетевой недоступности или ошибках сервиса выбрасывает SourceUnavailableError.
        """
        ...
