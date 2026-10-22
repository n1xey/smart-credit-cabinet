"""Простой rate-limiter для эндпоинта /auth/login.

Хранит счётчики в памяти (dict). Ключ — IP-адрес клиента.
Сбрасывается по скользящему минутному окну.
Для MVP достаточно; при масштабировании — заменить на Redis.
"""
import time
from collections import defaultdict
from threading import Lock


class InMemoryRateLimiter:
    """Thread-safe счётчик запросов за последнюю минуту по ключу."""

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
            self._counts[key] = [t for t in timestamps if t > cutoff]
            if len(self._counts[key]) >= self._limit:
                return False
            self._counts[key].append(now)
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
