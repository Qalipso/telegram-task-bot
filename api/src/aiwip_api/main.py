"""API entrypoint.

Stage 1 exposes only health endpoints; domain routers are added from Stage 3+.
- GET /health        liveness — never touches dependencies.
- GET /health/ready  readiness — verifies Postgres + Redis; 503 if degraded.
"""
from __future__ import annotations

from fastapi import FastAPI, Response, status

from aiwip_core import health
from aiwip_core.logging import get_logger

from aiwip_api.routers import auth as auth_router
from aiwip_api.routers import users as users_router

logger = get_logger("aiwip.api")

app = FastAPI(title="AI Work Intelligence Platform API", version="0.1.0")

app.include_router(auth_router.router)
app.include_router(users_router.router)


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
