"""Stage 4 — job consumer + scheduler (fake connector, real Postgres)."""
import datetime as dt

from aiwip_core import models as m
from aiwip_worker import consumer
from aiwip_worker.connectors.base import FetchedMessage
from aiwip_worker.connectors.fake import FakeConnector
from aiwip_worker.llm.client import FakeLLMClient

BASE = dt.datetime(2026, 6, 1, 12, 0, tzinfo=dt.timezone.utc)


def _fm(i: int) -> FetchedMessage:
    return FetchedMessage(
        external_message_id=i, sender_external_id=i, sender_username="u",
        sender_display_name="U", text="hi", sent_at=dt.datetime(2026, 6, 1, tzinfo=dt.timezone.utc), raw={},
    )


def _work_msg(i: int, text: str) -> FetchedMessage:
    return FetchedMessage(
        external_message_id=i, sender_external_id=i, sender_username="alice",
        sender_display_name="Alice", text=text, sent_at=BASE + dt.timedelta(minutes=i), raw={"id": i},
    )


_ONE_TASK = {
    "candidates": [{
        "type": "task", "title": "Ship the report", "summary": "Ship the report by Friday",
        "priority": "high", "due_date": "2026-06-05", "assignees": ["bob"],
        "source_message_ids": [1], "supporting_message_ids": [], "reasoning_summary": "explicit ask",
        "missing_fields": [],
        "confidence": {"item": 0.95, "context": 0.8, "assignee": 0.9, "priority": 0.7, "due_date": 0.8},
    }],
    "context_summary": "report", "context_confidence": 0.8,
}


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


def test_run_pipeline_extracts_candidates(db):
    """A sync that saves new messages chains into normalize + extract → candidates appear."""
    chat_ext = 8000
    db.add(m.Assignee(display_name="Bob", telegram_username="bob", is_active=True))
    db.flush()
    msgs = [_work_msg(1, "@bob ship the report by Friday, urgent")]

    run = consumer.run_pipeline(
        db, FakeConnector({chat_ext: msgs}), chat_ext, m.SyncTriggerType.manual,
        llm_client=FakeLLMClient(_ONE_TASK),
    )

    assert run.messages_saved == 1
    chat = db.query(m.Chat).filter_by(external_chat_id=chat_ext).one()
    assert db.query(m.Candidate).count() == 1
    # the analyzed messages are marked so a later empty sync won't re-extract them
    assert db.query(m.Message).filter_by(
        chat_id=chat.id, processing_status=m.MessageProcessingStatus.analyzed
    ).count() == 1


def test_run_pipeline_skips_extraction_when_nothing_saved(db):
    """Re-syncing the same messages saves 0 → extraction is skipped (no duplicate candidates)."""
    chat_ext = 8001
    db.add(m.Assignee(display_name="Bob", telegram_username="bob", is_active=True))
    db.flush()
    msgs = [_work_msg(1, "@bob ship the report by Friday, urgent")]
    conn = FakeConnector({chat_ext: msgs})

    consumer.run_pipeline(db, conn, chat_ext, m.SyncTriggerType.manual, llm_client=FakeLLMClient(_ONE_TASK))
    consumer.run_pipeline(db, conn, chat_ext, m.SyncTriggerType.scheduled, llm_client=FakeLLMClient(_ONE_TASK))

    assert db.query(m.Candidate).count() == 1  # not 2
    assert db.query(m.AiRun).filter_by(run_type=m.AiRunType.extraction).count() == 1  # extraction ran once


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
