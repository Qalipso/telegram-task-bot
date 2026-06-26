"""Phase 6 — BotApiConnector drains the Redis ingest buffer (real local Redis)."""
import datetime as dt

from aiwip_core import queue
from aiwip_core.redis_client import get_redis
from aiwip_worker.connectors.bot_api import BotApiConnector


def _rec(i: int, text: str = "hi") -> dict:
    return {
        "external_message_id": i,
        "sender_external_id": 100 + i,
        "sender_username": "u",
        "sender_display_name": "U",
        "text": text,
        "sent_at": dt.datetime(2026, 6, 1, tzinfo=dt.timezone.utc).isoformat(),
        "raw": {"id": i},
        "message_type": "text",
        "attachments": [],
    }


def test_drains_ascending_and_caps_limit():
    chat = 4001
    r = get_redis()
    r.delete(queue.botbuf_key(chat))
    for rec in (_rec(3), _rec(1), _rec(2)):  # push out of order to prove sorting
        queue.push_botbuf(chat, rec)
    out = BotApiConnector().fetch_messages(chat, after_message_id=None, limit=2)
    assert [m.external_message_id for m in out] == [1, 2]  # ascending, capped at 2
    assert out[0].text == "hi" and out[0].sender_username == "u"
    assert isinstance(out[0].sent_at, dt.datetime)
    r.delete(queue.botbuf_key(chat))


def test_filters_after_message_id_and_drains():
    chat = 4002
    r = get_redis()
    r.delete(queue.botbuf_key(chat))
    for rec in (_rec(1), _rec(2), _rec(3)):
        queue.push_botbuf(chat, rec)
    conn = BotApiConnector()
    out = conn.fetch_messages(chat, after_message_id=1, limit=200)
    assert [m.external_message_id for m in out] == [2, 3]
    # buffer is fully drained by the fetch — a second fetch returns nothing
    assert conn.fetch_messages(chat, after_message_id=1, limit=200) == []
    assert queue.botbuf_len(chat) == 0
    r.delete(queue.botbuf_key(chat))
