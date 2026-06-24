"""Stage 13 — end-to-end pipeline (fakes): sync → normalize → extract → approve → work item.

Exercises the whole backend loop deterministically (FakeConnector + FakeLLMClient).
"""
import datetime as dt

from aiwip_core import models as m
from aiwip_core import promotion
from aiwip_worker import consumer, extract, normalize
from aiwip_worker.connectors.base import FetchedMessage
from aiwip_worker.connectors.fake import FakeConnector
from aiwip_worker.llm.client import FakeLLMClient

BASE = dt.datetime(2026, 6, 1, 12, 0, tzinfo=dt.timezone.utc)


def test_full_pipeline_happy_path(db):
    chat_ext = 7000
    chat = m.Chat(connector_type=m.ConnectorType.telegram, external_chat_id=chat_ext)
    bob = m.Assignee(display_name="Bob", telegram_username="bob", is_active=True)
    db.add_all([chat, bob])
    db.flush()

    convo = ["Hi team", "@bob prepare the Q3 report by Friday, urgent"]
    fetched = [
        FetchedMessage(external_message_id=i, sender_external_id=i, sender_username="alice", sender_display_name="Alice", text=t, sent_at=BASE + dt.timedelta(minutes=i), raw={"id": i})
        for i, t in enumerate(convo, start=1)
    ]

    # 1. sync
    run = consumer.sync_chat(db, FakeConnector({chat_ext: fetched}), chat_ext, m.SyncTriggerType.manual)
    assert run.messages_saved == 2
    # 2. normalize
    normalize.normalize_pending(db)
    # 3. extract (fake LLM)
    out = {
        "candidates": [{
            "type": "task", "title": "Q3 report", "summary": "Prepare Q3 report", "priority": "high",
            "due_date": "2026-06-05", "assignees": ["bob"], "source_message_ids": [2], "supporting_message_ids": [],
            "reasoning_summary": "explicit ask", "missing_fields": [],
            "confidence": {"item": 0.95, "context": 0.8, "assignee": 0.9, "priority": 0.7, "due_date": 0.8},
        }],
        "context_summary": "q3", "context_confidence": 0.8,
    }
    created = extract.extract_candidates(db, chat.id, client=FakeLLMClient(out))
    assert len(created) == 1
    cand = created[0]
    assert cand.candidate_type == m.CandidateType.task
    assert db.query(m.CandidateAssignee).filter_by(candidate_id=cand.id).count() == 1
    # 4. approve → work item
    wi = promotion.approve_candidate(db, cand)
    db.flush()
    assert wi.status == m.WorkItemStatus.inbox and wi.source_candidate_id == cand.id
    assert db.query(m.WorkItemAssignee).filter_by(work_item_id=wi.id).count() == 1
    # 5. status transition
    wi.status = m.WorkItemStatus.in_progress
    db.flush()
    # 6. trace back to source messages (D16)
    primary = db.query(m.CandidateMessage).filter_by(candidate_id=cand.id, role=m.CandidateMessageRole.primary).all()
    assert len(primary) >= 1
    # 7. ai_run logged
    assert db.query(m.AiRun).filter_by(run_type=m.AiRunType.extraction).count() >= 1
    # 8. audit trail present
    actions = {a.action for a in db.query(m.AuditLog).all()}
    assert m.AuditAction.sync_started in actions and m.AuditAction.candidate_created in actions


def test_no_task_conversation_yields_no_candidates(db):
    chat = m.Chat(connector_type=m.ConnectorType.telegram, external_chat_id=7001)
    db.add(chat)
    db.flush()
    db.add(m.Message(chat_id=chat.id, external_message_id=1, message_type=m.MessageType.text, text_content="lol nice weather", normalized_content="lol nice weather", sent_at=BASE, raw_payload={"id": 1}, processing_status=m.MessageProcessingStatus.normalized))
    db.flush()
    created = extract.extract_candidates(db, chat.id, client=FakeLLMClient({"candidates": [], "context_summary": "chatter", "context_confidence": 0.3}))
    assert created == []
    assert db.query(m.AiRun).count() == 1  # still logged


def test_duplicate_message_resync_no_dups(db):
    chat = m.Chat(connector_type=m.ConnectorType.telegram, external_chat_id=7002)
    db.add(chat)
    db.flush()
    fetched = [FetchedMessage(external_message_id=1, sender_external_id=1, sender_username="a", sender_display_name="A", text="hi", sent_at=BASE, raw={"id": 1})]
    consumer.sync_chat(db, FakeConnector({7002: fetched}), 7002, m.SyncTriggerType.manual)
    consumer.sync_chat(db, FakeConnector({7002: fetched}), 7002, m.SyncTriggerType.scheduled)
    assert db.query(m.Message).filter_by(chat_id=chat.id).count() == 1
