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


def test_health_worker_ok_when_heartbeat_fresh(monkeypatch):
    monkeypatch.setattr(health, "worker_heartbeat_age", lambda: 5.0)
    resp = client.get("/health/worker")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["heartbeat_age_seconds"] == 5.0


def test_health_worker_503_when_heartbeat_stale(monkeypatch):
    monkeypatch.setattr(health, "worker_heartbeat_age", lambda: 10_000.0)
    resp = client.get("/health/worker")
    assert resp.status_code == 503
    assert resp.json()["status"] == "stale"


def test_health_worker_503_when_heartbeat_missing(monkeypatch):
    monkeypatch.setattr(health, "worker_heartbeat_age", lambda: None)
    resp = client.get("/health/worker")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "missing"
    assert body["heartbeat_age_seconds"] is None


def test_health_worker_503_when_redis_unreachable(monkeypatch):
    def _boom():
        raise ConnectionError("redis down")

    monkeypatch.setattr(health, "worker_heartbeat_age", _boom)
    resp = client.get("/health/worker")
    assert resp.status_code == 503
    assert resp.json()["status"] == "unknown"
