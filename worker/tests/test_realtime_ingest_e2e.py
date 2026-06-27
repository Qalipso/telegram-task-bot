"""Phase 6 — full forward-only path: bot ingest → buffer → process_job → candidate → notify."""
from aiwip_core import models as m
from aiwip_core import queue
from aiwip_core.redis_client import get_redis
from aiwip_worker import consumer
from aiwip_worker.llm.client import FakeLLMClient
from aiwip_bot import ingest

BOTLOCK_PREFIX = "aiwip:botlock:"

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


def _update(chat_id: int, mid: int, text: str) -> dict:
    return {"message": {"message_id": mid, "date": 1717243200 + mid,
                        "chat": {"id": chat_id},
                        "from": {"id": 700 + mid, "username": "alice", "first_name": "Alice"},
                        "text": text}}


class _SessionCtx:
    """Adapt the savepoint-isolated test session to process_job's `with sf() as db` contract."""
    def __init__(self, db):
        self._db = db

    def __enter__(self):
        return self._db

    def __exit__(self, *exc):
        return False


def test_forward_only_capture_to_candidate(db):
    ext = 9500
    r = get_redis()
    for key in (queue.botbuf_key(ext), f"{BOTLOCK_PREFIX}{ext}", queue.JOBS_KEY, queue.NOTIFY_KEY):
        r.delete(key)

    # bob exists + the chat is a configured bot chat (Phase 5 onboarding would have created it)
    db.add(m.Assignee(display_name="Bob", telegram_username="bob", is_active=True))
    consumer.get_or_create_chat(db, ext, connector_type=m.ConnectorType.telegram_bot)
    db.flush()

    # 1. two inbound messages arrive (forward-only) → buffered, ONE job enqueued (debounce)
    ingest.ingest_message(ext, ingest.record_from_update(_update(ext, 1, "@bob ship the report by Friday, urgent")),
                          debounce_seconds=60, is_configured=lambda c: True)
    ingest.ingest_message(ext, ingest.record_from_update(_update(ext, 2, "thanks!")),
                          debounce_seconds=60, is_configured=lambda c: True)
    assert queue.queue_length() == 1
    assert queue.botbuf_len(ext) == 2

    # 2. the worker drains the job (factory → BotApiConnector), with the test session + fake LLM
    job = queue.dequeue(timeout=2)
    consumer.process_job(job, session_factory=lambda: _SessionCtx(db), llm_client=FakeLLMClient(_ONE_TASK))

    # 3. messages persisted, gate fired, candidate created, notify emitted, buffer drained
    chat = db.query(m.Chat).filter_by(external_chat_id=ext, connector_type=m.ConnectorType.telegram_bot).one()
    assert db.query(m.Message).filter_by(chat_id=chat.id).count() == 2
    cand = db.query(m.Candidate).one()
    assert queue.dequeue_notify(timeout=2) == {"type": "bot.notify", "candidate_id": cand.id}
    assert queue.botbuf_len(ext) == 0

    for key in (queue.botbuf_key(ext), f"{BOTLOCK_PREFIX}{ext}", queue.JOBS_KEY, queue.NOTIFY_KEY):
        r.delete(key)


def test_process_job_auto_creates_missing_chat_as_telegram_bot(db):
    """Live-path guard: a brand-new captured group has NO Chat row; process_job must create it as
    telegram_bot so build_connector picks BotApiConnector (creating it as telegram would be rejected
    post-cutover). test_forward_only_capture_to_candidate pre-creates the chat and so misses this."""
    ext = 9600
    r = get_redis()
    for key in (queue.botbuf_key(ext), f"{BOTLOCK_PREFIX}{ext}", queue.JOBS_KEY, queue.NOTIFY_KEY):
        r.delete(key)
    db.add(m.Assignee(display_name="Bob", telegram_username="bob", is_active=True))
    db.flush()
    # NO chat pre-created — the bot captures into a brand-new group.
    ingest.ingest_message(
        ext, ingest.record_from_update(_update(ext, 1, "@bob ship the report by Friday, urgent")),
        debounce_seconds=60, is_configured=lambda c: True,
    )
    job = queue.dequeue(timeout=2)
    consumer.process_job(job, session_factory=lambda: _SessionCtx(db), llm_client=FakeLLMClient(_ONE_TASK))
    chat = db.query(m.Chat).filter_by(external_chat_id=ext).one()
    assert chat.connector_type == m.ConnectorType.telegram_bot  # auto-created as a bot chat
    assert db.query(m.Candidate).count() >= 1
    for key in (queue.botbuf_key(ext), f"{BOTLOCK_PREFIX}{ext}", queue.JOBS_KEY, queue.NOTIFY_KEY):
        r.delete(key)
