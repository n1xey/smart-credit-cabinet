"""Rate-limiter для защиты эндпоинта /auth/login от brute-force атак.

Архитектура:
- BaseRateLimiter: абстрактный интерфейс лимитера (метод скользящего окна).
- InMemoryRateLimiter: потокобезопасная in-memory реализация по умолчанию для MVP
  (согласно CLAUDE.md: "Без Redis/Kafka в MVP; в README описать как масштабировать").
- Поддерживает проверку по составным ключам (IP и account/email) для предотвращения
  как перебора с одного IP, так и распределённых атак на один аккаунт.
"""
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from threading import Lock


class BaseRateLimiter(ABC):
    """Абстрактный интерфейс rate-лимитера."""

    @abstractmethod
    def is_allowed(self, key: str) -> bool:
        """Проверяет, разрешён ли запрос по ключу, и регистрирует попытку."""
        raise NotImplementedError

    @abstractmethod
    def seconds_until_reset(self, key: str) -> int:
        """Возвращает число секунд до освобождения первого слота."""
        raise NotImplementedError


class InMemoryRateLimiter(BaseRateLimiter):
    """Thread-safe счётчик запросов за скользящее временное окно (в секундах) по ключу."""

    def __init__(self, limit: int, window_sec: int = 60) -> None:
        self._limit = limit
        self._window = window_sec
        self._counts: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def is_allowed(self, key: str) -> bool:
        """Возвращает True, если запрос в рамках лимита, и записывает его."""
        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            timestamps = self._counts[key]
            # убираем устаревшие записи
            valid = [t for t in timestamps if t > cutoff]
            if len(valid) >= self._limit:
                self._counts[key] = valid
                return False
            valid.append(now)
            self._counts[key] = valid
            return True

    def seconds_until_reset(self, key: str) -> int:
        """Сколько секунд до освобождения первого слота."""
        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            valid = [t for t in self._counts.get(key, []) if t > cutoff]
        if not valid:
            return 0
        return max(0, int(self._window - (now - valid[0])) + 1)
