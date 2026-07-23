"""Sentry init is a strict no-op without a DSN, active with one."""
import sys
import types

from aiwip_core import telemetry
from aiwip_core.config import settings


def test_disabled_without_dsn(monkeypatch):
    monkeypatch.setattr(settings, "sentry_dsn", None)
    assert telemetry.init_sentry("test") is False


def test_enabled_with_dsn(monkeypatch):
    # Stub the SDK so the test verifies the gating/wiring without network I/O.
    calls: dict = {}
    stub = types.SimpleNamespace(
        init=lambda **kw: calls.setdefault("init", kw),
        set_tag=lambda k, v: calls.setdefault("tag", (k, v)),
    )
    monkeypatch.setitem(sys.modules, "sentry_sdk", stub)
    monkeypatch.setattr(settings, "sentry_dsn", "https://key@example.ingest.sentry.io/1")

    assert telemetry.init_sentry("worker") is True
    assert calls["init"]["dsn"] == settings.sentry_dsn
    assert calls["init"]["environment"] == settings.app_env
    assert calls["tag"] == ("service", "worker")
