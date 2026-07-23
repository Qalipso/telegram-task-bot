"""Optional Sentry error tracking, shared by api / worker / bot.

No-op unless SENTRY_DSN is set — local dev and CI never talk to Sentry.
"""
from __future__ import annotations

from .config import settings
from .logging import get_logger

logger = get_logger("aiwip.telemetry")


def init_sentry(service: str) -> bool:
    """Initialise Sentry for one service. Returns True when active."""
    if not settings.sentry_dsn:
        return False
    import sentry_sdk  # imported lazily: only needed when a DSN is configured

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.app_env,
        # Errors are the point here; keep performance tracing off by default.
        traces_sample_rate=0.0,
        release=None,
    )
    sentry_sdk.set_tag("service", service)
    logger.info("sentry enabled for %s (env=%s)", service, settings.app_env)
    return True
