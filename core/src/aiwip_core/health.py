"""Liveness/readiness checks for Postgres and Redis."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from sqlalchemy import text

from .db import get_engine
from .redis_client import get_redis


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
