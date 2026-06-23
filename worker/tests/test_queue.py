"""Stage 4 — Redis job queue roundtrip (real local Redis)."""
from aiwip_core import queue
from aiwip_core.redis_client import get_redis


def test_enqueue_dequeue_roundtrip():
    get_redis().delete(queue.JOBS_KEY)
    queue.enqueue_sync(123, trigger="manual", user_id=7)
    assert queue.queue_length() == 1
    job = queue.dequeue(timeout=2)
    assert job is not None
    assert job["type"] == "telegram.sync"
    assert job["chat_id"] == 123
    assert job["user_id"] == 7
    assert queue.queue_length() == 0


def test_dequeue_empty_returns_none():
    get_redis().delete(queue.JOBS_KEY)
    assert queue.dequeue(timeout=1) is None
