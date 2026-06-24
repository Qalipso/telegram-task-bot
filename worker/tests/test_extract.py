"""Stage 8 — OpenAI extraction pipeline (deterministic FakeLLMClient, real Postgres)."""
import datetime as dt

from aiwip_core import models as m
from aiwip_worker import extract
from aiwip_worker.llm.client import FakeLLMClient

BASE = dt.datetime(2026, 6, 1, 12, 0, tzinfo=dt.timezone.utc)


def _chat(db, ext=900):
    c = m.Chat(connector_type=m.ConnectorType.telegram, external_chat_id=ext)
    db.add(c)
    db.flush()
    return c


def _msg(db, chat, ext, minutes=0, text="please do X by Friday", sender="alice"):
    msg = m.Message(
        chat_id=chat.id, external_message_id=ext, message_type=m.MessageType.text,
        text_content=text, normalized_content=text, sender_username=sender,
        sent_at=BASE + dt.timedelta(minutes=minutes), raw_payload={"id": ext},
        processing_status=m.MessageProcessingStatus.normalized,
    )
    db.add(msg)
    db.flush()
    return msg


def _output(item=0.95, assignees=None, source=None, priority="high", due="2026-06-05", ctype="task"):
    return {
        "candidates": [{
            "type": ctype, "title": "Do X", "summary": "Do X by Friday",
            "priority": priority, "due_date": due, "assignees": assignees or [],
            "source_message_ids": source or [], "supporting_message_ids": [],
            "reasoning_summary": "explicit ask", "missing_fields": [],
            "confidence": {"item": item, "context": 0.8, "assignee": 0.7, "priority": 0.6, "due_date": 0.7},
        }],
        "context_summary": "X discussion", "context_confidence": 0.8,
    }


def test_creates_candidate_with_links_and_ai_run(db):
    chat = _chat(db)
    msg = _msg(db, chat, 1)
    bob = m.Assignee(display_name="Bob", telegram_username="bob")
    db.add(bob)
    db.flush()
    created = extract.extract_candidates(db, chat.id, client=FakeLLMClient(_output(assignees=["bob"], source=[1])))
    assert len(created) == 1
    c = created[0]
    assert c.candidate_type == m.CandidateType.task
    assert c.title == "Do X" and c.summary
    assert c.priority == m.Priority.high
    assert c.status == m.CandidateStatus.new
    assert c.task_confidence == 0.95
    cms = db.query(m.CandidateMessage).filter_by(candidate_id=c.id).all()
    assert any(x.message_id == msg.id and x.role == m.CandidateMessageRole.primary for x in cms)
    cas = db.query(m.CandidateAssignee).filter_by(candidate_id=c.id).all()
    assert len(cas) == 1 and cas[0].assignee_id == bob.id and cas[0].is_primary
    runs = db.query(m.AiRun).all()
    assert len(runs) == 1 and runs[0].status == "success" and runs[0].run_type == m.AiRunType.extraction
    assert runs[0].input_hash and runs[0].prompt_version == "v2"
    assert db.query(m.WorkItem).count() == 0  # AI never creates work items


def test_invalid_json_does_not_crash(db):
    chat = _chat(db, 901)
    _msg(db, chat, 1)
    created = extract.extract_candidates(db, chat.id, client=FakeLLMClient({}, status="invalid_json"))
    assert created == []
    runs = db.query(m.AiRun).all()
    assert len(runs) == 1 and runs[0].status == "invalid_json"


def test_low_confidence_skipped_but_logged(db):
    chat = _chat(db, 902)
    _msg(db, chat, 1)
    created = extract.extract_candidates(db, chat.id, client=FakeLLMClient(_output(item=0.5, source=[1])))
    assert created == []
    assert db.query(m.AiRun).count() == 1


def test_needs_review_band(db):
    chat = _chat(db, 903)
    _msg(db, chat, 1)
    created = extract.extract_candidates(db, chat.id, client=FakeLLMClient(_output(item=0.8, source=[1])))
    assert len(created) == 1 and created[0].status == m.CandidateStatus.needs_review


def test_invalid_priority_to_none_and_due_null(db):
    chat = _chat(db, 904)
    _msg(db, chat, 1)
    created = extract.extract_candidates(db, chat.id, client=FakeLLMClient(_output(priority="weird", due=None, source=[1])))
    assert created[0].priority is None and created[0].due_date is None


def test_unresolved_assignee_marks_missing_and_needs_review(db):
    chat = _chat(db, 905)
    _msg(db, chat, 1)
    created = extract.extract_candidates(db, chat.id, client=FakeLLMClient(_output(item=0.95, assignees=["ghost"], source=[1])))
    c = created[0]
    assert db.query(m.CandidateAssignee).filter_by(candidate_id=c.id).count() == 0
    assert "assignee" in (c.missing_fields or [])
    assert c.status == m.CandidateStatus.needs_review


def test_due_date_parsed(db):
    chat = _chat(db, 906)
    _msg(db, chat, 1)
    created = extract.extract_candidates(db, chat.id, client=FakeLLMClient(_output(due="2026-06-05", source=[1])))
    assert created[0].due_date is not None and created[0].due_date.year == 2026
