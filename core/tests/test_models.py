"""Stage 2 — schema constraints, relationships, and a seed graph (real Postgres)."""
import pytest
from sqlalchemy.exc import IntegrityError

from aiwip_core import models as m


def _chat(session, ext=1000):
    c = m.Chat(connector_type=m.ConnectorType.telegram, external_chat_id=ext, title="t")
    session.add(c)
    session.flush()
    return c


def test_unique_message_per_chat(session):
    """Test #16 — uniqueness of chat_id + external_message_id."""
    c = _chat(session)
    session.add(m.Message(chat_id=c.id, external_message_id=1, message_type=m.MessageType.text))
    session.flush()
    session.add(m.Message(chat_id=c.id, external_message_id=1, message_type=m.MessageType.text))
    with pytest.raises(IntegrityError):
        session.flush()


def test_candidate_links_multiple_messages(session):
    """Test #59 — a candidate links to multiple source messages with roles."""
    c = _chat(session, 1001)
    m1 = m.Message(chat_id=c.id, external_message_id=1, message_type=m.MessageType.text)
    m2 = m.Message(chat_id=c.id, external_message_id=2, message_type=m.MessageType.text)
    session.add_all([m1, m2])
    session.flush()
    cand = m.Candidate(candidate_type=m.CandidateType.task, title="do x", status=m.CandidateStatus.new)
    session.add(cand)
    session.flush()
    session.add_all([
        m.CandidateMessage(candidate_id=cand.id, message_id=m1.id, role=m.CandidateMessageRole.primary),
        m.CandidateMessage(candidate_id=cand.id, message_id=m2.id, role=m.CandidateMessageRole.context),
    ])
    session.flush()
    session.refresh(cand)
    assert len(cand.candidate_messages) == 2
    assert {cm.role for cm in cand.candidate_messages} == {
        m.CandidateMessageRole.primary,
        m.CandidateMessageRole.context,
    }


def test_candidate_multiple_assignees(session):
    """Test #60 — a candidate can have multiple assignees (with exactly one primary)."""
    cand = m.Candidate(candidate_type=m.CandidateType.task, title="multi", status=m.CandidateStatus.needs_review)
    a1, a2 = m.Assignee(display_name="A"), m.Assignee(display_name="B")
    session.add_all([cand, a1, a2])
    session.flush()
    session.add_all([
        m.CandidateAssignee(candidate_id=cand.id, assignee_id=a1.id, confidence=0.9, is_primary=True),
        m.CandidateAssignee(candidate_id=cand.id, assignee_id=a2.id, confidence=0.4, is_primary=False),
    ])
    session.flush()
    session.refresh(cand)
    assert len(cand.candidate_assignees) == 2
    assert sum(1 for ca in cand.candidate_assignees if ca.is_primary) == 1


def test_work_item_multiple_assignees_and_one_per_candidate(session):
    """Test #69 — multi-assignee work item; and the 1 candidate → 1 work_item invariant."""
    cand = m.Candidate(candidate_type=m.CandidateType.task, title="x", status=m.CandidateStatus.approved)
    session.add(cand)
    session.flush()
    a1, a2 = m.Assignee(display_name="A"), m.Assignee(display_name="B")
    session.add_all([a1, a2])
    session.flush()
    wi = m.WorkItem(source_candidate_id=cand.id, type=m.WorkItemType.task, title="x", status=m.WorkItemStatus.inbox)
    session.add(wi)
    session.flush()
    session.add_all([
        m.WorkItemAssignee(work_item_id=wi.id, assignee_id=a1.id, is_primary=True),
        m.WorkItemAssignee(work_item_id=wi.id, assignee_id=a2.id, is_primary=False),
    ])
    session.flush()
    session.refresh(wi)
    assert len(wi.work_item_assignees) == 2
    assert sum(1 for x in wi.work_item_assignees if x.is_primary) == 1

    # second work_item for the same candidate must violate the unique constraint
    session.add(m.WorkItem(source_candidate_id=cand.id, type=m.WorkItemType.task, status=m.WorkItemStatus.inbox))
    with pytest.raises(IntegrityError):
        session.flush()


def test_tags_via_join_tables(session):
    label = m.Label(name="backend", color="#00f")
    cand = m.Candidate(candidate_type=m.CandidateType.idea, status=m.CandidateStatus.new)
    session.add_all([label, cand])
    session.flush()
    session.add(m.CandidateLabel(candidate_id=cand.id, label_id=label.id))
    session.flush()
    session.refresh(cand)
    assert [cl.label.name for cl in cand.candidate_labels] == ["backend"]

    # work-item side of the same tag vocabulary (work_item_labels join)
    wi = m.WorkItem(source_candidate_id=cand.id, type=m.WorkItemType.idea, status=m.WorkItemStatus.inbox)
    session.add(wi)
    session.flush()
    session.add(m.WorkItemLabel(work_item_id=wi.id, label_id=label.id))
    session.flush()
    session.refresh(wi)
    assert [wl.label.name for wl in wi.work_item_labels] == ["backend"]


def test_assignee_user_unique(session):
    """D24 — one user ↔ at most one assignee."""
    u = m.User(email="u@x.io", role=m.UserRole.assignee)
    session.add(u)
    session.flush()
    session.add(m.Assignee(user_id=u.id, display_name="one"))
    session.flush()
    session.add(m.Assignee(user_id=u.id, display_name="two"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_priority_nullable(session):
    """Priority NULL is allowed (a candidate is still created)."""
    cand = m.Candidate(candidate_type=m.CandidateType.request, status=m.CandidateStatus.needs_review, priority=None)
    session.add(cand)
    session.flush()
    assert cand.priority is None


def test_seed_full_graph(session):
    """Seed-data test — a coherent end-to-end graph touching most tables persists,
    and a work item traces back to its source messages via its candidate (D16)."""
    admin = m.User(email="admin@x.io", display_name="Admin", role=m.UserRole.admin)
    conn = m.ConnectorAccount(connector_type=m.ConnectorType.telegram, name="primary", credentials_ref="env:TELEGRAM_SESSION")
    chat = m.Chat(connector_type=m.ConnectorType.telegram, external_chat_id=42, title="Team")
    session.add_all([admin, conn, chat])
    session.flush()

    state = m.SyncState(chat_id=chat.id, last_external_message_id=10)
    run = m.SyncRun(trigger_type=m.SyncTriggerType.manual, status=m.SyncRunStatus.success, messages_read=2, candidates_created=1, created_by_user_id=admin.id)
    msg = m.Message(chat_id=chat.id, external_message_id=11, message_type=m.MessageType.text, text_content="Ship the report by Friday", normalized_content="Ship the report by Friday")
    session.add_all([state, run, msg])
    session.flush()

    assignee = m.Assignee(telegram_username="bob", display_name="Bob", aliases=["Bobby", "Robert"])
    label = m.Label(name="report")
    session.add_all([assignee, label])
    session.flush()

    cand = m.Candidate(
        candidate_type=m.CandidateType.task, title="Ship report", summary="Ship the report",
        priority=m.Priority.high, status=m.CandidateStatus.approved, task_confidence=0.92,
        missing_fields=["due_date"], context_summary="window of 1", model_name="gpt-4o-mini", prompt_version="v1",
    )
    session.add(cand)
    session.flush()
    session.add_all([
        m.CandidateMessage(candidate_id=cand.id, message_id=msg.id, role=m.CandidateMessageRole.primary),
        m.CandidateAssignee(candidate_id=cand.id, assignee_id=assignee.id, confidence=0.8, is_primary=True),
        m.CandidateLabel(candidate_id=cand.id, label_id=label.id),
        m.AiRun(run_type=m.AiRunType.extraction, model_provider="openai", model_name="gpt-4o-mini", prompt_version="v1", input_hash="abc123", tokens_input=100, tokens_output=20, cost=0.0003, status="success"),
    ])
    wi = m.WorkItem(source_candidate_id=cand.id, type=m.WorkItemType.task, title="Ship report", summary="Ship the report", priority=m.Priority.high, status=m.WorkItemStatus.inbox, reasoning="approved", confidence=0.92, created_by_user_id=admin.id)
    session.add(wi)
    session.flush()
    session.add_all([
        m.WorkItemAssignee(work_item_id=wi.id, assignee_id=assignee.id, is_primary=True),
        m.WorkItemLabel(work_item_id=wi.id, label_id=label.id),
        m.AuditLog(actor_user_id=admin.id, action=m.AuditAction.candidate_approved, entity_type=m.AuditEntityType.candidate, entity_id=cand.id, after_value={"status": "approved"}),
        m.EvaluationCase(source_message_ids=[msg.id], input_payload={"text": "..."}, expected_output={"type": "task"}, result=m.EvaluationResult.pending),
    ])
    session.flush()

    session.refresh(wi)
    assert wi.source_candidate.id == cand.id
    assert [cm.message_id for cm in wi.source_candidate.candidate_messages] == [msg.id]
