"""Stage 1 — worker smoke tests (host-side)."""
from aiwip_core import health
from aiwip_worker import main


def test_run_once_reports_snapshot(monkeypatch):
    monkeypatch.setattr(health, "check_database", lambda: health.CheckResult(True, "connected"))
    monkeypatch.setattr(health, "check_redis", lambda: health.CheckResult(True, "connected"))
    snapshot = main.run_once()
    assert snapshot == {"database": True, "redis": True}


def test_run_once_degraded(monkeypatch):
    monkeypatch.setattr(health, "check_database", lambda: health.CheckResult(False, "down"))
    monkeypatch.setattr(health, "check_redis", lambda: health.CheckResult(True, "connected"))
    snapshot = main.run_once()
    assert snapshot["database"] is False
