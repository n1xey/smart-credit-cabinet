from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.db import get_engine

router = APIRouter(tags=["System"])


@router.get("/health/live")
def live() -> dict:
    return {"status": "ok"}


@router.get("/health/ready")
def ready():
    """Готов, если БД отвечает и миграции применены (есть строка в alembic_version)."""
    checks = {"database": "ok", "migrations": "ok"}
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
            try:
                if conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).first() is None:
                    checks["migrations"] = "not_applied"
            except Exception:
                checks["migrations"] = "not_applied"
    except Exception:
        checks = {"database": "unavailable", "migrations": "unknown"}
    ok = all(v == "ok" for v in checks.values())
    return JSONResponse(
        status_code=200 if ok else 503,
        content={"status": "ready" if ok else "not_ready", "checks": checks},
    )
