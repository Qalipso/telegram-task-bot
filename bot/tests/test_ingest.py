"""Phase 6 — bot ingest: forward-only buffer push + debounced enqueue + configure gate."""
import datetime as dt

from aiwip_core import queue
from aiwip_core.redis_client import get_redis
from aiwip_bot import ingest

BOTLOCK_PREFIX = "aiwip:botlock:"


def _update(chat_id: int, mid: int, text: str = "hi") -> dict:
    return {
        "message": {
            "message_id": mid,
            "date": 1717243200,  # 2024-06-01T12:00:00Z epoch
            "chat": {"id": chat_id},
            "from": {"id": 500 + mid, "username": "u", "first_name": "U"},
            "text": text,
        }
    }


def test_record_from_update_maps_fields():
    rec = ingest.record_from_update(_update(7777, 9, "ship it"))
    assert rec["external_message_id"] == 9
    assert rec["sender_external_id"] == 509
    assert rec["sender_username"] == "u"
    assert rec["sender_display_name"] == "U"
    assert rec["text"] == "ship it"
    assert rec["message_type"] == "text"
    dt.datetime.fromisoformat(rec["sent_at"])  # parseable ISO string


def test_debounce_coalesces_n_messages_to_one_job(monkeypatch):
    chat = 7800
    r = get_redis()
    r.delete(queue.botbuf_key(chat))
    r.delete(f"{BOTLOCK_PREFIX}{chat}")
    r.delete(queue.JOBS_KEY)

    enqueued = []
    monkeypatch.setattr("aiwip_core.queue.enqueue_sync", lambda *a, **k: enqueued.append((a, k)))

    for mid in (1, 2, 3):
        ingest.ingest_message(chat, ingest.record_from_update(_update(chat, mid)),
                              debounce_seconds=60, is_configured=lambda c: True)

    assert queue.botbuf_len(chat) == 3      # all three buffered
    assert len(enqueued) == 1               # exactly one job for the burst
    assert enqueued[0][0][0] == chat        # enqueue_sync(chat, ...)
    r.delete(queue.botbuf_key(chat))
    r.delete(f"{BOTLOCK_PREFIX}{chat}")


def test_unconfigured_chat_captures_nothing(monkeypatch):
    chat = 7801
    r = get_redis()
    r.delete(queue.botbuf_key(chat))
    r.delete(f"{BOTLOCK_PREFIX}{chat}")
    enqueued = []
    monkeypatch.setattr("aiwip_core.queue.enqueue_sync", lambda *a, **k: enqueued.append(1))

    did = ingest.ingest_message(chat, ingest.record_from_update(_update(chat, 1)),
                                debounce_seconds=60, is_configured=lambda c: False)

    assert did is False
    assert queue.botbuf_len(chat) == 0   # not pushed (GATE)
    assert enqueued == []                 # not enqueued
    r.delete(queue.botbuf_key(chat))
