"""Stage 1 — settings load + override."""
from aiwip_core.config import Settings


def test_defaults_load():
    s = Settings()
    assert s.app_env  # non-empty default
    assert s.database_url.startswith("postgresql")
    assert s.redis_url.startswith("redis://")
    # Secrets are optional until their stage wires them.
    assert s.telegram_api_id is None
    assert s.openai_api_key is None


def test_env_override(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("WORKER_HEARTBEAT_SECONDS", "5")
    s = Settings()
    assert s.log_level == "DEBUG"
    assert s.worker_heartbeat_seconds == 5
