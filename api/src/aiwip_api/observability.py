"""Prometheus metrics for the API.

Own CollectorRegistry (not the global default) so test runs and multiple
app instances never double-register collectors.
"""
from __future__ import annotations

import time

from fastapi import FastAPI, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from aiwip_core import health
from aiwip_core.queue import JOBS_KEY
from aiwip_core.redis_client import get_redis

registry = CollectorRegistry()

http_requests_total = Counter(
    "aiwip_http_requests_total",
    "HTTP requests processed by the API",
    ["method", "path", "status"],
    registry=registry,
)
http_request_duration_seconds = Histogram(
    "aiwip_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "path"],
    registry=registry,
)
worker_heartbeat_age_seconds = Gauge(
    "aiwip_worker_heartbeat_age_seconds",
    "Seconds since the worker's last heartbeat (-1 = never recorded)",
    registry=registry,
)
queue_depth = Gauge(
    "aiwip_queue_depth",
    "Jobs waiting in the Redis queue (-1 = Redis unreachable)",
    registry=registry,
)


def _route_template(request: Request) -> str:
    """Label by route template (/candidates/{id}), not raw path — bounded cardinality."""
    route = request.scope.get("route")
    return getattr(route, "path", request.url.path if request.url.path == "/metrics" else "unmatched")


def install_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def _track(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        path = _route_template(request)
        http_requests_total.labels(request.method, path, str(response.status_code)).inc()
        http_request_duration_seconds.labels(request.method, path).observe(
            time.perf_counter() - start
        )
        return response


def render_metrics() -> Response:
    """Refresh the scrape-time gauges and render the exposition format."""
    try:
        age = health.worker_heartbeat_age()
        worker_heartbeat_age_seconds.set(-1 if age is None else age)
    except Exception:  # noqa: BLE001 — Redis down: report unknown, keep /metrics up
        worker_heartbeat_age_seconds.set(-1)
    try:
        queue_depth.set(get_redis().llen(JOBS_KEY))
    except Exception:  # noqa: BLE001
        queue_depth.set(-1)
    return Response(content=generate_latest(registry), media_type=CONTENT_TYPE_LATEST)
