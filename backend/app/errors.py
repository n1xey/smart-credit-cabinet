"""Единый формат ошибок: {"error": {"code", "message", "details"}}."""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.enums import ErrorCode
from app.logging import correlation_id_var

log = logging.getLogger("app.errors")

_STATUS_TO_CODE = {
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    409: ErrorCode.CONFLICT,
    413: ErrorCode.PAYLOAD_TOO_LARGE,
    429: ErrorCode.RATE_LIMITED,
}


class ApiError(Exception):
    def __init__(self, status_code: int, code: ErrorCode, message: str, details: list | None = None):
        super().__init__(message)
        self.status_code, self.code, self.message, self.details = status_code, code, message, details or []


def error_body(code: ErrorCode, message: str, details: list | None = None) -> dict:
    return {"error": {"code": code.value, "message": message, "details": details or []}}


def _response(status: int, code: ErrorCode, message: str, details: list | None = None) -> JSONResponse:
    headers = {}
    if cid := correlation_id_var.get():
        headers["X-Correlation-ID"] = cid
    return JSONResponse(status_code=status, content=error_body(code, message, details), headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return _response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        details = [
            {"field": ".".join(str(p) for p in e["loc"] if p not in ("body", "query", "path")), "message": e["msg"]}
            for e in exc.errors()
        ]
        return _response(422, ErrorCode.VALIDATION_ERROR, "Некорректные данные запроса", details)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        code = _STATUS_TO_CODE.get(exc.status_code) or (
            ErrorCode.INTERNAL_ERROR if exc.status_code >= 500 else ErrorCode.VALIDATION_ERROR
        )
        return _response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        log.exception("unhandled_error")  # трассировка только в лог, клиенту деталей не отдаём
        return _response(500, ErrorCode.INTERNAL_ERROR, "Внутренняя ошибка сервера")
