"""Stage 1 — backend health check tests (run host-side, no services needed)."""
from fastapi.testclient import TestClient

from aiwip_core import health
from aiwip_api.main import app

client = TestClient(app)


def test_health_live_returns_ok():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "api"


def test_health_ready_ok_when_all_checks_pass(monkeypatch):
    monkeypatch.setattr(health, "check_database", lambda: health.CheckResult(True, "connected"))
    monkeypatch.setattr(health, "check_redis", lambda: health.CheckResult(True, "connected"))
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


def test_health_ready_503_when_a_check_fails(monkeypatch):
    monkeypatch.setattr(health, "check_database", lambda: health.CheckResult(False, "down"))
    monkeypatch.setattr(health, "check_redis", lambda: health.CheckResult(True, "connected"))
    resp = client.get("/health/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["checks"]["database"]["ok"] is False
