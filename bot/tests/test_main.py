"""Phase 3 — bot main: readiness snapshot + token-less (CI-safe) boot."""
from aiwip_core import health

from aiwip_bot import config, main


def test_run_once_reports_redis_and_api_flags(monkeypatch):
    monkeypatch.setattr(health, "check_redis", lambda: health.CheckResult(True, "connected"))
    # API probe is injected so the test never hits the network.
    snapshot = main.run_once(api_probe=lambda: True)
    assert snapshot == {"redis": True, "api": True, "long_poll": False}


def test_run_once_api_down(monkeypatch):
    monkeypatch.setattr(health, "check_redis", lambda: health.CheckResult(True, "connected"))
    snapshot = main.run_once(api_probe=lambda: False)
    assert snapshot["api"] is False


def test_long_poll_enabled_flag_reflects_token(monkeypatch):
    monkeypatch.setattr(health, "check_redis", lambda: health.CheckResult(True, "connected"))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    config.get_bot_settings.cache_clear()
    snapshot = main.run_once(api_probe=lambda: True)
    assert snapshot["long_poll"] is True
    config.get_bot_settings.cache_clear()  # reset for other tests


def test_run_returns_immediately_without_token(monkeypatch):
    """Token-less boot must not raise and must not block (CI-safe mode)."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    config.get_bot_settings.cache_clear()
    monkeypatch.setattr(health, "check_redis", lambda: health.CheckResult(True, "connected"))
    # once=True makes run() do a single readiness pass and return (no infinite loop).
    main.run(once=True, api_probe=lambda: True)
    config.get_bot_settings.cache_clear()
