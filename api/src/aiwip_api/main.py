"""API entrypoint.

Stage 1 exposes only health endpoints; domain routers are added from Stage 3+.
- GET /health        liveness — never touches dependencies.
- GET /health/ready  readiness — verifies Postgres + Redis; 503 if degraded.
- GET /health/worker worker liveness via Redis heartbeat; 503 if stale/missing.
- GET /metrics       Prometheus exposition (HTTP counters, heartbeat age, queue depth).
"""
from __future__ import annotations

from fastapi import FastAPI, Response, status

from aiwip_core import health
from aiwip_core.config import settings
from aiwip_core.logging import get_logger

from aiwip_api import observability

from aiwip_api import analytics as analytics_router
from aiwip_api.routers import assignees as assignees_router
from aiwip_api.routers import audit as audit_router
from aiwip_api.routers import auth as auth_router
from aiwip_api.routers import candidates as candidates_router
from aiwip_api.routers import evaluation as evaluation_router
from aiwip_api.routers import labels as labels_router
from aiwip_api.routers import sync as sync_router
from aiwip_api.routers import users as users_router
from aiwip_api.routers import work_items as work_items_router

logger = get_logger("aiwip.api")

app = FastAPI(title="AI Work Intelligence Platform API", version="0.1.0")

observability.install_middleware(app)

app.include_router(auth_router.router)
app.include_router(users_router.router)
app.include_router(sync_router.router)
app.include_router(assignees_router.router)
app.include_router(candidates_router.router)
app.include_router(work_items_router.router)
app.include_router(labels_router.router)
app.include_router(audit_router.router)
app.include_router(evaluation_router.router)
app.include_router(analytics_router.router)


@app.get("/health")
def health_live() -> dict:
    return {"status": "ok", "service": "api", "version": app.version}


@app.get("/health/ready")
def health_ready(response: Response) -> dict:
    checks = {
        "database": health.check_database(),
        "redis": health.check_redis(),
    }
    ready = all(c.ok for c in checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        logger.warning("readiness degraded: %s", {k: v.detail for k, v in checks.items() if not v.ok})
    return {
        "status": "ready" if ready else "degraded",
        "checks": {name: result.as_dict() for name, result in checks.items()},
    }


@app.get("/health/worker")
def health_worker(response: Response) -> dict:
    """Worker liveness for external uptime monitors: 503 unless the worker's
    Redis heartbeat is fresher than worker_heartbeat_max_age_seconds."""
    max_age = settings.worker_heartbeat_max_age_seconds
    try:
        age = health.worker_heartbeat_age()
    except Exception as exc:  # noqa: BLE001 — Redis down: worker state unknown
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unknown", "detail": f"{type(exc).__name__}: {exc}"}
    if age is None or age > max_age:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        logger.warning("worker heartbeat %s (max_age=%ss)", "missing" if age is None else f"stale: {age:.0f}s", max_age)
    return {
        "status": "ok" if age is not None and age <= max_age else ("missing" if age is None else "stale"),
        "heartbeat_age_seconds": None if age is None else round(age, 1),
        "max_age_seconds": max_age,
    }


@app.get("/metrics")
def metrics() -> Response:
    return observability.render_metrics()
