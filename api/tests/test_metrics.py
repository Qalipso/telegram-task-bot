"""Prometheus /metrics endpoint tests (heartbeat + queue gauges are monkeypatched)."""
from fastapi.testclient import TestClient

from aiwip_api import observability
from aiwip_api.main import app

client = TestClient(app)


class _FakeRedis:
    def __init__(self, depth: int):
        self._depth = depth

    def llen(self, key: str) -> int:
        return self._depth


def test_metrics_exposes_core_series(monkeypatch):
    monkeypatch.setattr(observability.health, "worker_heartbeat_age", lambda: 12.0)
    monkeypatch.setattr(observability, "get_redis", lambda: _FakeRedis(depth=7))

    resp = client.get("/metrics")
    assert resp.status_code == 200
    text = resp.text
    assert "aiwip_worker_heartbeat_age_seconds 12.0" in text
    assert "aiwip_queue_depth 7.0" in text
    assert "aiwip_http_requests_total" in text
    assert "aiwip_http_request_duration_seconds" in text


def test_metrics_http_counter_increments(monkeypatch):
    monkeypatch.setattr(observability.health, "worker_heartbeat_age", lambda: 1.0)
    monkeypatch.setattr(observability, "get_redis", lambda: _FakeRedis(depth=0))

    client.get("/health")
    resp = client.get("/metrics")
    assert 'aiwip_http_requests_total{method="GET",path="/health",status="200"}' in resp.text


def test_metrics_reports_negative_one_when_redis_down(monkeypatch):
    def _boom():
        raise ConnectionError("redis down")

    monkeypatch.setattr(observability.health, "worker_heartbeat_age", _boom)

    def _no_redis():
        raise ConnectionError("redis down")

    monkeypatch.setattr(observability, "get_redis", _no_redis)

    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "aiwip_worker_heartbeat_age_seconds -1.0" in resp.text
    assert "aiwip_queue_depth -1.0" in resp.text
