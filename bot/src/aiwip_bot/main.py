"""Bot service entrypoint (design spec §10).

Phase 3 scope: the service must BOOT (token-less / CI-safe) and report readiness.
The full getUpdates long-poll loop, bot.notify consumption, debounce timers, and
the callback dispatch wiring are owned by a SINGLE later phase — Phase 4 (Confirm
UX) — which builds this same main.py into the running dispatcher. They are not
split across phases. Here run() either:
  * starts a minimal long-poll only when a token is configured, or
  * with no token, logs that long-poll is disabled and stays alive as a
    readiness-only process (so the container is healthy in CI / no-token envs).

run_once() mirrors aiwip_worker.main.run_once(): a connectivity snapshot.
"""
from __future__ import annotations

import time
from typing import Callable

from aiwip_core import health
from aiwip_core.logging import get_logger

from .api_client import ApiClient, ConversationalApiError
from .config import get_bot_settings

logger = get_logger("aiwip.bot")


def _default_api_probe() -> bool:
    """Probe API readiness via GET /api/auth/me (login + cookie replay)."""
    s = get_bot_settings()
    client = ApiClient(s.bot_api_base, s.bot_admin_email, s.bot_admin_password)
    try:
        client.me()
        return True
    except ConversationalApiError as exc:
        logger.warning("api probe failed: %s", exc.message)
        return False
    finally:
        client.close()


def run_once(api_probe: Callable[[], bool] = _default_api_probe) -> dict:
    """One readiness cycle. Returns {redis, api, long_poll}."""
    s = get_bot_settings()
    redis_ok = health.check_redis().ok
    api_ok = api_probe()
    long_poll = bool(s.telegram_bot_token)
    snapshot = {"redis": redis_ok, "api": api_ok, "long_poll": long_poll}
    if redis_ok and api_ok:
        logger.info("bot ready %s", snapshot)
    else:
        logger.warning("bot degraded %s", snapshot)
    return snapshot


def run(once: bool = False, api_probe: Callable[[], bool] = _default_api_probe) -> None:
    """Main loop.

    Phase 3: a readiness heartbeat. With a token configured the long-poll is
    started by Phase 4; here we only log intent so the no-token path is proven
    CI-safe. `once=True` runs a single readiness pass and returns (for tests).
    """
    s = get_bot_settings()
    if not s.telegram_bot_token:
        logger.info("TELEGRAM_BOT_TOKEN not set — long-poll disabled (CI-safe boot)")
    else:
        logger.info("TELEGRAM_BOT_TOKEN present — long-poll will start in Phase 4")

    while True:
        run_once(api_probe=api_probe)
        if once:
            return
        time.sleep(s.bot_poll_interval_seconds)


if __name__ == "__main__":
    run()
