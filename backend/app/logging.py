"""Структурные JSON-логи. Без персональных данных и токенов."""
import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone

correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)
application_id_var: ContextVar[str | None] = ContextVar("application_id", default=None)

_SENSITIVE = ("password", "token", "authorization", "secret", "email", "inn", "passport", "phone", "full_name")
_STD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


def redact(value):
    """Рекурсивно маскирует значения чувствительных ключей."""
    if isinstance(value, dict):
        return {k: "***" if any(s in str(k).lower() for s in _SENSITIVE) else redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": correlation_id_var.get(),
            "application_id": application_id_var.get(),
        }
        extra = {k: v for k, v in record.__dict__.items() if k not in _STD_ATTRS}
        payload.update(redact(extra))
        if record.exc_info and record.exc_info[0]:
            payload["exc_type"] = record.exc_info[0].__name__
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    logging.getLogger("uvicorn.access").disabled = True  # access-лог пишет наш middleware
