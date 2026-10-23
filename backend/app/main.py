import yaml
from fastapi import FastAPI

from app.api import applications, auth, company, documents, feed, health, products
from app.config import get_settings
from app.errors import install_error_handlers
from app.logging import setup_logging
from app.middleware import CorrelationIdMiddleware

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)

    app = FastAPI(title="Credit Cabinet API", docs_url="/docs", openapi_url="/openapi.json", redoc_url=None)
    app.add_middleware(CorrelationIdMiddleware)
    install_error_handlers(app)

    app.include_router(health.router)  # health — на корне, без префикса
    # Бизнес-роутеры:
    app.include_router(auth.router, prefix=API_PREFIX)
    app.include_router(products.router, prefix=API_PREFIX)
    app.include_router(company.router, prefix=API_PREFIX)
    app.include_router(applications.router, prefix=API_PREFIX)
    app.include_router(documents.router, prefix=API_PREFIX)
    app.include_router(feed.router, prefix=API_PREFIX)

    def contract_openapi() -> dict:
        """Источник схемы — контракт docs/api/openapi.yaml, а не автогенерация."""
        if app.openapi_schema is None:
            app.openapi_schema = yaml.safe_load(settings.openapi_path.read_text(encoding="utf-8"))
        return app.openapi_schema

    app.openapi = contract_openapi  # type: ignore[method-assign]
    return app


app = create_app()
