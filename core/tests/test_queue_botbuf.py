"""Phase 6 — bot ingest buffer + notify queue helpers (real local Redis)."""
import json

from aiwip_core import queue
from aiwip_core.redis_client import get_redis


def test_botbuf_key_is_per_chat():
    assert queue.botbuf_key(555) == "aiwip:botbuf:555"


def test_push_botbuf_appends_and_len_counts():
    r = get_redis()
    r.delete(queue.botbuf_key(900))
    queue.push_botbuf(900, {"external_message_id": 1, "text": "hi"})
    queue.push_botbuf(900, {"external_message_id": 2, "text": "yo"})
    assert queue.botbuf_len(900) == 2
    raw = r.lrange(queue.botbuf_key(900), 0, -1)
    assert {json.loads(x)["external_message_id"] for x in raw} == {1, 2}
    r.delete(queue.botbuf_key(900))


def test_notify_roundtrip():
    r = get_redis()
    r.delete(queue.NOTIFY_KEY)
    queue.enqueue_notify(42)
    msg = queue.dequeue_notify(timeout=2)
    assert msg == {"type": "bot.notify", "candidate_id": 42}
    assert r.llen(queue.NOTIFY_KEY) == 0
    r.delete(queue.NOTIFY_KEY)
