"""Stage 1 — settings load + override."""
import pytest
from pydantic import ValidationError

from aiwip_core.config import Settings


def test_defaults_load():
    # _env_file=None: test pure defaults/env, independent of any developer .env.
    s = Settings(_env_file=None)
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


def test_insecure_secret_key_default_allowed_in_local(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    s = Settings(_env_file=None, app_env="local")
    assert s.secret_key == "dev-insecure-change-me"


def test_insecure_secret_key_default_rejected_outside_local(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(_env_file=None, app_env="production")


def test_real_secret_key_allowed_outside_local(monkeypatch):
    s = Settings(_env_file=None, app_env="production", secret_key="a-real-random-secret")
    assert s.secret_key == "a-real-random-secret"
