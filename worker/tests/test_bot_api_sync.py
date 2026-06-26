"""Phase 6 — BotApiConnector through the real run_sync persist path (dedup + state)."""
import datetime as dt

from aiwip_core import models as m
from aiwip_core import queue
from aiwip_core.redis_client import get_redis
from aiwip_worker import sync
from aiwip_worker.connectors.bot_api import BotApiConnector


def _rec(i: int) -> dict:
    return {
        "external_message_id": i, "sender_external_id": i, "sender_username": "u",
        "sender_display_name": "U", "text": "hi",
        "sent_at": dt.datetime(2026, 6, 1, tzinfo=dt.timezone.utc).isoformat(),
        "raw": {"id": i}, "message_type": "text", "attachments": [],
    }


def _chat(db, ext: int) -> m.Chat:
    c = m.Chat(connector_type=m.ConnectorType.telegram, external_chat_id=ext, title="c")
    db.add(c)
    db.flush()
    return c


def test_run_sync_with_bot_connector_dedups(db):
    ext = 4100
    r = get_redis()
    r.delete(queue.botbuf_key(ext))
    chat = _chat(db, ext)

    for rec in (_rec(1), _rec(2)):
        queue.push_botbuf(ext, rec)
    run1 = sync.run_sync(db, BotApiConnector(), chat, m.SyncTriggerType.manual)
    assert run1.messages_saved == 2

    # bot re-delivers an old id (1) plus a new one (3); dedup must keep only 3
    for rec in (_rec(1), _rec(3)):
        queue.push_botbuf(ext, rec)
    run2 = sync.run_sync(db, BotApiConnector(), chat, m.SyncTriggerType.scheduled)
    assert run2.messages_saved == 1
    assert db.query(m.Message).filter_by(chat_id=chat.id).count() == 3
    state = db.query(m.SyncState).filter_by(chat_id=chat.id).one()
    assert state.last_external_message_id == 3
    r.delete(queue.botbuf_key(ext))
