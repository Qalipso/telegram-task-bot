"""Phase 3 — bot config keys (spec §10). Named test_bot_config to avoid a basename clash
with core/tests/test_config.py (pytest prepend import mode has no __init__.py in tests dirs)."""
from aiwip_bot.config import BotSettings


def test_defaults_match_spec_section_10():
    s = BotSettings()
    # Secrets are Optional so the service can boot without them (CI-safe mode).
    assert s.telegram_bot_token is None
    assert s.bot_admin_email is None
    assert s.bot_admin_password is None
    # Non-secret defaults from spec §10.
    assert s.bot_api_base == "http://api:8000"
    assert s.bot_poll_interval_seconds == 30
    assert s.bot_debounce_seconds == 60
    assert s.bot_digest_interval_seconds == 300
    assert s.auto_band == 0.90
    assert s.review_band == 0.60
    assert s.quiet_hours_start_utc == 22
    assert s.quiet_hours_end_utc == 8
    assert s.quiet_hours_enabled is True


def test_env_override_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("BOT_API_BASE", "http://localhost:8000")
    # @lru_cache on the module-level accessor must not mask env in tests:
    from aiwip_bot import config as cfg
    cfg.get_bot_settings.cache_clear()
    s = cfg.get_bot_settings()
    assert s.telegram_bot_token == "123:abc"
    assert s.bot_api_base == "http://localhost:8000"
    cfg.get_bot_settings.cache_clear()  # reset for other tests


def test_review_chat_id_default_and_env_override(monkeypatch):
    from aiwip_bot import config as cfg
    assert cfg.BotSettings().bot_review_chat_id is None  # optional; no import-time error
    monkeypatch.setenv("BOT_REVIEW_CHAT_ID", "424242")
    cfg.get_bot_settings.cache_clear()
    assert cfg.get_bot_settings().bot_review_chat_id == 424242
    cfg.get_bot_settings.cache_clear()
