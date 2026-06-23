"""Stage 4 — sync engine tests with a fake connector (no network)."""
import datetime as dt

from aiwip_core import models as m
from aiwip_worker import sync
from aiwip_worker.connectors.base import FetchedMessage
from aiwip_worker.connectors.fake import FakeConnector


def _fm(i: int, text: str = "hi") -> FetchedMessage:
    return FetchedMessage(
        external_message_id=i,
        sender_external_id=100 + i,
        sender_username="u",
        sender_display_name="U",
        text=text,
        sent_at=dt.datetime(2026, 6, 1, tzinfo=dt.timezone.utc),
        raw={"id": i},
    )


def _chat(db, ext: int) -> m.Chat:
    c = m.Chat(connector_type=m.ConnectorType.telegram, external_chat_id=ext, title="c")
    db.add(c)
    db.flush()
    return c


def test_sync_saves_new_messages(db):
    chat = _chat(db, 555)
    run = sync.run_sync(db, FakeConnector({555: [_fm(1), _fm(2), _fm(3)]}), chat, m.SyncTriggerType.manual)
    assert run.status == m.SyncRunStatus.success
    assert run.messages_read == 3 and run.messages_saved == 3
    assert db.query(m.Message).filter_by(chat_id=chat.id).count() == 3
    state = db.query(m.SyncState).filter_by(chat_id=chat.id).one()
    assert state.last_external_message_id == 3
    assert state.last_successful_sync_at is not None


def test_resync_reads_only_new_and_no_duplicates(db):
    chat = _chat(db, 556)
    sync.run_sync(db, FakeConnector({556: [_fm(1), _fm(2)]}), chat, m.SyncTriggerType.manual)
    run2 = sync.run_sync(db, FakeConnector({556: [_fm(1), _fm(2), _fm(3)]}), chat, m.SyncTriggerType.scheduled)
    assert run2.messages_read == 1  # only id > last_external_message_id (2)
    assert run2.messages_saved == 1
    assert db.query(m.Message).filter_by(chat_id=chat.id).count() == 3  # no duplicates of 1,2


def test_failed_sync_records_error_and_preserves_state(db):
    chat = _chat(db, 557)

    class BoomConnector:
        def fetch_messages(self, *a, **k):
            raise RuntimeError("telegram down")

    run = sync.run_sync(db, BoomConnector(), chat, m.SyncTriggerType.manual)
    assert run.status == m.SyncRunStatus.failed
    assert "telegram down" in (run.error_message or "")
    state = db.query(m.SyncState).filter_by(chat_id=chat.id).one()
    assert "telegram down" in (state.last_error or "")
    assert state.last_external_message_id is None  # not advanced on failure
    assert db.query(m.Message).filter_by(chat_id=chat.id).count() == 0


def test_run_recorded_with_counts(db):
    chat = _chat(db, 558)
    sync.run_sync(db, FakeConnector({558: [_fm(1)]}), chat, m.SyncTriggerType.manual)
    runs = db.query(m.SyncRun).all()
    assert len(runs) == 1
    assert runs[0].messages_read == 1 and runs[0].messages_saved == 1
