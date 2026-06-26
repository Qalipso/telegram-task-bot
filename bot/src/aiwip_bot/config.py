"""Bot service settings (design spec §10), loaded from environment / .env.

Mirrors aiwip_core.config: pydantic-settings BaseSettings + @lru_cache accessor.
Secrets (bot token, bot-admin credentials) are Optional so the container boots
without them — that is the CI-safe / no-token boot mode the spec requires. The
poll loop refuses to start the long-poll without a token (see main.py) but the
process still comes up and reports readiness.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # --- Telegram Bot API (spec §10) — Optional so the service boots token-less. ---
    telegram_bot_token: str | None = None

    # --- This service -> platform API (spec §10). ---
    bot_api_base: str = "http://api:8000"
    bot_admin_email: str | None = None
    bot_admin_password: str | None = None
    # Where confirm cards + digests are sent (admin DM / private review group). Required at runtime
    # when a token is set — enforced in telegram_app.run_app, NOT here (this model loads at import).
    bot_review_chat_id: int | None = None
    bot_getupdates_timeout: int = 30

    # --- Loop cadences (spec §10). ---
    bot_poll_interval_seconds: int = 30
    bot_debounce_seconds: int = 60
    bot_digest_interval_seconds: int = 300

    # --- Confidence bands (spec §6.2 / §10). ---
    auto_band: float = 0.90
    review_band: float = 0.60

    # --- Quiet hours (spec §6.2, UTC per decision D4). Default ON. ---
    quiet_hours_enabled: bool = True
    quiet_hours_start_utc: int = 22
    quiet_hours_end_utc: int = 8


@lru_cache
def get_bot_settings() -> BotSettings:
    return BotSettings()


bot_settings = get_bot_settings()
