"""Application settings, loaded from environment / .env (pydantic-settings).

Secrets (Telegram, OpenAI) are Optional so the system boots without them; they
are only required by the stages that use them (Telegram = Stage 4, OpenAI = Stage 8).
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator

INSECURE_SECRET_KEY_DEFAULT = "dev-insecure-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # Runtime
    app_env: str = "local"
    log_level: str = "INFO"

    # Connections. Defaults target host-side runs (localhost); docker-compose
    # overrides them to the in-network hostnames "postgres" / "redis".
    database_url: str = "postgresql+psycopg://aiwip:aiwip@localhost:5432/aiwip"
    redis_url: str = "redis://localhost:6379/0"

    # Worker
    worker_heartbeat_seconds: int = 30
    sync_interval_seconds: int = 6 * 3600  # scheduled sync cadence (system-spec §8)

    # Auth (Stage 3)
    secret_key: str = INSECURE_SECRET_KEY_DEFAULT

    # Telegram (Stage 4) — Optional until the connector is wired.
    telegram_api_id: int | None = None
    telegram_api_hash: str | None = None
    telegram_phone: str | None = None
    telegram_session: str | None = None
    telegram_chat_id: int | None = None

    # OpenAI (Stage 8) — Optional until the AI pipeline is wired.
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"

    @model_validator(mode="after")
    def _reject_insecure_secret_outside_local(self) -> "Settings":
        if self.app_env != "local" and self.secret_key == INSECURE_SECRET_KEY_DEFAULT:
            raise ValueError(
                "SECRET_KEY is still the insecure placeholder "
                f"({INSECURE_SECRET_KEY_DEFAULT!r}) with APP_ENV={self.app_env!r}. "
                "Set a real SECRET_KEY in .env before running outside local dev."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
