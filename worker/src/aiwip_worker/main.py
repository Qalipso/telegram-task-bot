"""Worker entrypoint.

Stage 1 is a connectivity heartbeat only: verify Postgres + Redis are reachable
and log a heartbeat each cycle. The job loop (sync, normalize, context, AI) is
added from Stage 4 onward.
"""
from __future__ import annotations

import time

from aiwip_core import health
from aiwip_core.config import settings
from aiwip_core.logging import get_logger

logger = get_logger("aiwip.worker")


def run_once() -> dict:
    """One heartbeat cycle. Returns a connectivity snapshot."""
    db = health.check_database()
    redis = health.check_redis()
    snapshot = {"database": db.ok, "redis": redis.ok}
    if db.ok and redis.ok:
        logger.info("heartbeat ok %s", snapshot)
    else:
        logger.warning("heartbeat degraded db=%s redis=%s", db.detail, redis.detail)
    return snapshot


def run() -> None:
    logger.info("worker starting (heartbeat every %ss)", settings.worker_heartbeat_seconds)
    while True:
        run_once()
        time.sleep(settings.worker_heartbeat_seconds)


if __name__ == "__main__":
    run()
