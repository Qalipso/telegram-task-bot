"""Phase 6 — run_pipeline emits bot.notify for each new candidate."""
import datetime as dt

from aiwip_core import models as m
from aiwip_core import queue
from aiwip_core.redis_client import get_redis
from aiwip_worker import consumer
from aiwip_worker.connectors.base import FetchedMessage
from aiwip_worker.connectors.fake import FakeConnector
from aiwip_worker.llm.client import FakeLLMClient

BASE = dt.datetime(2026, 6, 1, 12, 0, tzinfo=dt.timezone.utc)

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


def _msgs():
    return [FetchedMessage(
        external_message_id=1, sender_external_id=1, sender_username="alice",
        sender_display_name="Alice", text="@bob ship the report by Friday, urgent",
        sent_at=BASE + dt.timedelta(minutes=1), raw={"id": 1},
    )]


def test_run_pipeline_emits_bot_notify(db):
    r = get_redis()
    r.delete(queue.NOTIFY_KEY)
    ext = 8200
    db.add(m.Assignee(display_name="Bob", telegram_username="bob", is_active=True))
    db.flush()
    consumer.run_pipeline(
        db, FakeConnector({ext: _msgs()}), ext, m.SyncTriggerType.manual,
        llm_client=FakeLLMClient(_ONE_TASK),
    )
    cand = db.query(m.Candidate).one()
    notify = queue.dequeue_notify(timeout=2)
    assert notify == {"type": "bot.notify", "candidate_id": cand.id}
    assert r.llen(queue.NOTIFY_KEY) == 0
    r.delete(queue.NOTIFY_KEY)


def test_run_pipeline_no_notify_when_nothing_saved(db):
    """A re-sync that saves 0 messages skips extraction → emits no notify."""
    r = get_redis()
    r.delete(queue.NOTIFY_KEY)
    ext = 8201
    db.add(m.Assignee(display_name="Bob", telegram_username="bob", is_active=True))
    db.flush()
    conn = FakeConnector({ext: _msgs()})
    consumer.run_pipeline(db, conn, ext, m.SyncTriggerType.manual, llm_client=FakeLLMClient(_ONE_TASK))
    queue.dequeue_notify(timeout=2)  # drain the first (legit) notify
    r.delete(queue.NOTIFY_KEY)

    consumer.run_pipeline(db, conn, ext, m.SyncTriggerType.scheduled, llm_client=FakeLLMClient(_ONE_TASK))
    assert r.llen(queue.NOTIFY_KEY) == 0  # nothing saved → no extraction → no notify
    r.delete(queue.NOTIFY_KEY)
