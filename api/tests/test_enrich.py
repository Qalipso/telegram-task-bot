"""Enrichment: work items / candidates carry assignee names + source chat."""
from aiwip_api import auth
from aiwip_core import models as m


def _login_admin(client, db, email="admin@x.io"):
    u = m.User(email=email, role=m.UserRole.admin, password_hash=auth.hash_password("pw123456"))
    db.add(u)
    db.flush()
    client.post("/api/auth/login", json={"email": email, "password": "pw123456"})
    return u


def _chat(db, external_chat_id=-100500, title="Team Chat"):
    c = m.Chat(connector_type=m.ConnectorType.telegram_bot, external_chat_id=external_chat_id, title=title)
    db.add(c)
    db.flush()
    return c


def _candidate_in_chat(db, chat, title="do the thing", status=m.CandidateStatus.new):
    cand = m.Candidate(candidate_type=m.CandidateType.task, title=title, status=status)
    db.add(cand)
    db.flush()
    msg = m.Message(
        chat_id=chat.id, external_message_id=1, message_type=m.MessageType.text, text_content=title
    )
    db.add(msg)
    db.flush()
    db.add(m.CandidateMessage(candidate_id=cand.id, message_id=msg.id, role=m.CandidateMessageRole.primary))
    db.flush()
    return cand


def test_candidate_list_carries_source_chat(client, db):
    _login_admin(client, db)
    chat = _chat(db, external_chat_id=-100777, title="Eng Team")
    _candidate_in_chat(db, chat, title="ship it")
    row = client.get("/api/candidates").json()[0]
    assert row["source_chat_id"] == -100777
    assert row["source_chat_title"] == "Eng Team"


def test_work_item_list_carries_assignees_and_chat(client, db):
    _login_admin(client, db)
    chat = _chat(db, external_chat_id=-100888, title="Ops")
    cand = _candidate_in_chat(db, chat, title="fix prod", status=m.CandidateStatus.approved)
    wi = m.WorkItem(source_candidate_id=cand.id, type=m.WorkItemType.task, title="fix prod",
                    status=m.WorkItemStatus.inbox)
    db.add(wi)
    db.flush()
    a1 = m.Assignee(display_name="Эдуард", telegram_username="edot", is_active=True)
    a2 = m.Assignee(display_name="Иван", telegram_username="ivan", is_active=True)
    db.add_all([a1, a2])
    db.flush()
    db.add(m.WorkItemAssignee(work_item_id=wi.id, assignee_id=a1.id, is_primary=True))
    db.add(m.WorkItemAssignee(work_item_id=wi.id, assignee_id=a2.id, is_primary=False))
    db.flush()

    row = client.get("/api/work-items").json()[0]
    assert row["assignees"][0] == "Эдуард"  # primary first
    assert "Иван" in row["assignees"]
    assert row["source_chat_id"] == -100888
    assert row["source_chat_title"] == "Ops"


def test_work_item_without_assignee_or_messages_is_safe(client, db):
    _login_admin(client, db)
    cand = m.Candidate(candidate_type=m.CandidateType.task, title="orphan", status=m.CandidateStatus.approved)
    db.add(cand)
    db.flush()
    wi = m.WorkItem(source_candidate_id=cand.id, type=m.WorkItemType.task, title="orphan",
                    status=m.WorkItemStatus.inbox)
    db.add(wi)
    db.flush()
    row = client.get("/api/work-items").json()[0]
    assert row["assignees"] == []
    assert row["source_chat_id"] is None
    assert row["source_chat_title"] is None


def test_sync_status_exposes_external_chat_id(client, db):
    _login_admin(client, db)
    chat = _chat(db, external_chat_id=-100999, title="Sync Chat")
    db.add(m.SyncState(chat_id=chat.id, last_external_message_id=42))
    db.flush()
    states = client.get("/api/sync/status").json()["states"]
    assert any(s["external_chat_id"] == -100999 and s["chat_title"] == "Sync Chat" for s in states)
