from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Вся конфигурация только из env (см. .env.example)."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    app_env: str = "dev"
    log_level: str = "INFO"
    demo_mode: bool = False
    database_url: str = "postgresql+psycopg://credit:credit@localhost:5432/credit"
    openapi_path: Path = Field(default=_REPO_ROOT / "docs" / "api" / "openapi.yaml")

    # auth
    jwt_secret: str = "change-me-in-env"
    jwt_ttl_minutes: int = 60
    login_rate_limit_per_minute: int = 10

    # таймеры процесса
    needs_info_ttl_hours: int = 72
    offer_ttl_hours: int = 72
    signing_ttl_hours: int = 72
    max_info_rounds: int = 2
    job_lock_timeout_sec: int = 120

    # документы
    uploads_dir: Path = Path("/data/uploads")
    doc_max_size_mb: int = 10
    doc_allowed_mime: str = "application/pdf,image/png,image/jpeg"

    # внешние сервисы (моки)
    bki_url: str = "http://mock-bki:8001"
    egrul_url: str = "http://mock-egrul:8002"
    ai_enabled: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
