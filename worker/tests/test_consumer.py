"""Stage 4 — job consumer + scheduler (fake connector, real Postgres)."""
import datetime as dt

from aiwip_core import models as m
from aiwip_worker import consumer
from aiwip_worker.connectors.base import FetchedMessage
from aiwip_worker.connectors.fake import FakeConnector


def _fm(i: int) -> FetchedMessage:
    return FetchedMessage(
        external_message_id=i, sender_external_id=i, sender_username="u",
        sender_display_name="U", text="hi", sent_at=dt.datetime(2026, 6, 1, tzinfo=dt.timezone.utc), raw={},
    )


def test_sync_chat_creates_chat_and_syncs(db):
    run = consumer.sync_chat(db, FakeConnector({999: [_fm(1), _fm(2)]}), 999, m.SyncTriggerType.manual)
    assert run.status == m.SyncRunStatus.success and run.messages_saved == 2
    chat = db.query(m.Chat).filter_by(external_chat_id=999).one()
    assert db.query(m.Message).filter_by(chat_id=chat.id).count() == 2


def test_should_requeue_bounds():
    assert consumer.should_requeue(m.SyncRunStatus.failed, 0) is True
    assert consumer.should_requeue(m.SyncRunStatus.failed, 1) is True
    assert consumer.should_requeue(m.SyncRunStatus.failed, 2) is False  # 2+1 == MAX_ATTEMPTS
    assert consumer.should_requeue(m.SyncRunStatus.success, 0) is False


def test_enqueue_scheduled_syncs_active_only(db, monkeypatch):
    calls = []
    monkeypatch.setattr("aiwip_core.queue.enqueue_sync", lambda *a, **k: calls.append((a, k)))
    db.add(m.Chat(connector_type=m.ConnectorType.telegram, external_chat_id=111, is_active=True))
    db.add(m.Chat(connector_type=m.ConnectorType.telegram, external_chat_id=222, is_active=False))
    db.flush()
    n = consumer.enqueue_scheduled_syncs(db)
    assert n == 1  # inactive chat excluded
    assert calls[0][0][0] == 111
    assert calls[0][1].get("trigger") == "scheduled"
