"""Liveness/readiness checks for Postgres and Redis, plus the worker heartbeat."""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass

from sqlalchemy import text

from .db import get_engine
from .redis_client import get_redis

# Worker liveness: the worker refreshes this key each heartbeat cycle; the API
# exposes its age so an external uptime monitor can alert on a dead worker.
WORKER_HEARTBEAT_KEY = "aiwip:worker:heartbeat"


@dataclass
class CheckResult:
    ok: bool
    detail: str

    def as_dict(self) -> dict:
        return asdict(self)


def check_database() -> CheckResult:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return CheckResult(True, "connected")
    except Exception as exc:  # noqa: BLE001 - report any failure as not-ready
        return CheckResult(False, f"{type(exc).__name__}: {exc}")


def check_redis() -> CheckResult:
    try:
        get_redis().ping()
        return CheckResult(True, "connected")
    except Exception as exc:  # noqa: BLE001
        return CheckResult(False, f"{type(exc).__name__}: {exc}")


def record_worker_heartbeat() -> None:
    """Called by the worker each cycle — even when Postgres/Redis checks are
    degraded, a refreshed key still proves the process itself is alive."""
    get_redis().set(WORKER_HEARTBEAT_KEY, str(time.time()))


def worker_heartbeat_age() -> float | None:
    """Seconds since the worker's last heartbeat, or None if never recorded."""
    raw = get_redis().get(WORKER_HEARTBEAT_KEY)
    if raw is None:
        return None
    return max(0.0, time.time() - float(raw))
