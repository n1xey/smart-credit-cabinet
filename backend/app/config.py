import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
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

    # auth: обязательный секрет из env; должен сохраняться между рестартами сервиса
    jwt_secret: str = Field(
        ...,
        min_length=16,
        description="JWT secret key from env; must be static across restarts",
    )
    jwt_ttl_minutes: int = 60
    login_rate_limit_per_minute: int = 10

    # таймеры процесса и воркера
    needs_info_ttl_hours: int = 72
    offer_ttl_hours: int = 72
    signing_ttl_hours: int = 72
    max_info_rounds: int = 2
    job_lock_timeout_sec: int = 120
    job_max_attempts: int = 3
    job_base_backoff_sec: int = 2
    watchdog_interval_sec: int = 60


    # документы
    uploads_dir: Path = Path("/data/uploads")
    doc_max_size_mb: int = 10
    doc_allowed_mime: str = "application/pdf,image/png,image/jpeg"

    # внешние сервисы (моки)
    bki_url: str = "http://mock-bki:8001"
    egrul_url: str = "http://mock-egrul:8002"
    ai_enabled: bool = False

    @model_validator(mode="after")
    def validate_security_and_critical_settings(self) -> "Settings":
        is_prod = self.app_env.lower() in ("prod", "production", "stage", "staging")
        if is_prod:
            if self.jwt_secret == "change-me-in-env" or len(self.jwt_secret) < 32:
                raise ValueError(
                    "JWT_SECRET must be securely configured via environment variable in production "
                    "(minimum 32 characters, not default placeholder)"
                )

        if self.jwt_ttl_minutes <= 0:
            raise ValueError("jwt_ttl_minutes must be positive")
        if self.login_rate_limit_per_minute <= 0:
            raise ValueError("login_rate_limit_per_minute must be positive")

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
