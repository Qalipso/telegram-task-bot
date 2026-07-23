"""Worker heartbeat roundtrip against real Redis (skipped when Redis is absent)."""
import pytest

from aiwip_core import health
from aiwip_core.redis_client import get_redis


def _redis_available() -> bool:
    try:
        get_redis().ping()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _redis_available(), reason="Redis not reachable")
def test_heartbeat_roundtrip():
    get_redis().delete(health.WORKER_HEARTBEAT_KEY)
    assert health.worker_heartbeat_age() is None

    health.record_worker_heartbeat()
    age = health.worker_heartbeat_age()
    assert age is not None
    assert 0.0 <= age < 5.0
