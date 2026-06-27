"""API entrypoint.

Stage 1 exposes only health endpoints; domain routers are added from Stage 3+.
- GET /health        liveness — never touches dependencies.
- GET /health/ready  readiness — verifies Postgres + Redis; 503 if degraded.
"""
from __future__ import annotations

from fastapi import FastAPI, Response, status

from aiwip_core import health
from aiwip_core.logging import get_logger

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
