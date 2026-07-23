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
    try:
        health.record_worker_heartbeat()
    except Exception:  # noqa: BLE001 — heartbeat write must not kill the loop
        logger.exception("failed to record worker heartbeat")
    snapshot = {"database": db.ok, "redis": redis.ok}
    if db.ok and redis.ok:
        logger.info("heartbeat ok %s", snapshot)
    else:
        logger.warning("heartbeat degraded db=%s redis=%s", db.detail, redis.detail)
    return snapshot


def run() -> None:
    """Main loop: drain the job queue, with a periodic heartbeat.

    Bot-only after the Phase-6 cutover (Decisions §16.1): the 6h scheduler is gone — the bot is the
    single writer, enqueueing forward-only sync jobs as messages arrive.
    """
    from . import consumer

    logger.info("worker starting: queue consumer")
    last_heartbeat = 0.0
    while True:
        try:
            consumer.consume_once(timeout=5)
        except Exception:  # noqa: BLE001 — a bad job must not kill the worker
            logger.exception("job processing error")

        now = time.monotonic()
        if now - last_heartbeat >= settings.worker_heartbeat_seconds:
            run_once()
            last_heartbeat = now


if __name__ == "__main__":
    run()
