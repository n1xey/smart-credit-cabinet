"""Correlation-ID и access-лог (чистый ASGI: корректно работает со стримингом/SSE)."""
import logging
import re
import time
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders

from app.logging import application_id_var, correlation_id_var

log = logging.getLogger("app.access")
_CID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class CorrelationIdMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        incoming = Headers(scope=scope).get("x-correlation-id")
        cid = incoming if incoming and _CID_RE.match(incoming) else str(uuid4())
        # Контекст не сбрасываем: на каждый запрос свой task, а обработчик 500 читает значение уже после нас.
        correlation_id_var.set(cid)
        application_id_var.set(None)
        status = {"code": 0}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                headers = MutableHeaders(scope=message)
                if "x-correlation-id" not in headers:
                    headers.append("X-Correlation-ID", cid)
            await send(message)

        started = time.perf_counter()
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            log.info(
                "request",
                extra={
                    "method": scope["method"],
                    "path": scope["path"],  # без query-строки
                    "status": status["code"],
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
