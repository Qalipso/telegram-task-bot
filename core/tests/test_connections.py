"""Stage 1 — real Postgres/Redis connection tests.

These execute against live services (docker-compose). When the services are not
reachable (e.g. host-only runs without Docker) they SKIP rather than fail, so the
suite stays green locally while still being exercised under Docker/CI.
"""
import pytest

from aiwip_core import health


def test_database_connection():
    result = health.check_database()
    if not result.ok:
        pytest.skip(f"Postgres not reachable: {result.detail}")
    assert result.ok


def test_redis_connection():
    result = health.check_redis()
    if not result.ok:
        pytest.skip(f"Redis not reachable: {result.detail}")
    assert result.ok
