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
    """Main loop: drain the job queue, with a periodic heartbeat and scheduled-sync enqueue."""
    from aiwip_core.db import get_sessionmaker

    from . import consumer

    logger.info(
        "worker starting: queue consumer + scheduler (every %ss)", settings.sync_interval_seconds
    )
    last_heartbeat = 0.0
    last_schedule = time.monotonic()  # wait a full interval before the first scheduled run
    while True:
        try:
            consumer.consume_once(timeout=5)
        except Exception:  # noqa: BLE001 — a bad job must not kill the worker
            logger.exception("job processing error")

        now = time.monotonic()
        if now - last_heartbeat >= settings.worker_heartbeat_seconds:
            run_once()
            last_heartbeat = now
        if now - last_schedule >= settings.sync_interval_seconds:
            try:
                with get_sessionmaker()() as db:
                    n = consumer.enqueue_scheduled_syncs(db)
                logger.info("scheduled sync for %s active chat(s)", n)
            except Exception:  # noqa: BLE001
                logger.exception("scheduler error")
            last_schedule = now


if __name__ == "__main__":
    run()
