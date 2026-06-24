"""Stage 9 — candidate review API (list/detail/edit/approve/reject) + audit."""
from aiwip_api import auth
from aiwip_core import models as m


def _login(client, db, role):
    email = f"{role.value}@x.io"
    db.add(m.User(email=email, role=role, password_hash=auth.hash_password("pw123456")))
    db.flush()
    client.post("/api/auth/login", json={"email": email, "password": "pw123456"})


def _seed_candidate(db, status=m.CandidateStatus.new):
    chat = m.Chat(connector_type=m.ConnectorType.telegram, external_chat_id=900)
    db.add(chat)
    db.flush()
    msg = m.Message(
        chat_id=chat.id, external_message_id=1, message_type=m.MessageType.text,
        text_content="do x", processing_status=m.MessageProcessingStatus.normalized,
    )
    db.add(msg)
    db.flush()
    cand = m.Candidate(
        candidate_type=m.CandidateType.task, title="Do X", summary="do the thing",
        priority=m.Priority.high, status=status, task_confidence=0.9, reasoning_summary="r", missing_fields=[],
    )
    db.add(cand)
    db.flush()
    db.add(m.CandidateMessage(candidate_id=cand.id, message_id=msg.id, role=m.CandidateMessageRole.primary))
    assignee = m.Assignee(display_name="Bob", telegram_username="bob")
    db.add(assignee)
    db.flush()
    db.add(m.CandidateAssignee(candidate_id=cand.id, assignee_id=assignee.id, is_primary=True))
    db.flush()
    return cand


def test_list_and_detail(client, db):
    _login(client, db, m.UserRole.admin)
    cand = _seed_candidate(db)
    assert len(client.get("/api/candidates").json()) >= 1
    assert len(client.get("/api/candidates?status=new").json()) >= 1
    detail = client.get(f"/api/candidates/{cand.id}").json()
    assert detail["candidate"]["title"] == "Do X"
    assert len(detail["assignees"]) == 1 and len(detail["messages"]) == 1


def test_edit_sets_edited_and_audits(client, db):
    _login(client, db, m.UserRole.admin)
    cand = _seed_candidate(db)
    r = client.patch(f"/api/candidates/{cand.id}", json={"title": "Edited"})
    assert r.status_code == 200 and r.json()["title"] == "Edited" and r.json()["status"] == "edited"
    audits = db.query(m.AuditLog).filter_by(action=m.AuditAction.candidate_edited).all()
    assert len(audits) == 1
    assert audits[0].before_value["title"] == "Do X" and audits[0].after_value["title"] == "Edited"


def test_approve_creates_work_item_and_promotes_assignees(client, db):
    _login(client, db, m.UserRole.admin)
    cand = _seed_candidate(db)
    r = client.post(f"/api/candidates/{cand.id}/approve")
    assert r.status_code == 201, r.text
    wi = r.json()
    assert wi["status"] == "inbox" and wi["type"] == "task" and wi["title"] == "Do X"
    assert wi["source_candidate_id"] == cand.id
    wias = db.query(m.WorkItemAssignee).filter_by(work_item_id=wi["id"]).all()
    assert len(wias) == 1 and wias[0].is_primary
    db.refresh(cand)
    assert cand.status == m.CandidateStatus.approved
    assert db.query(m.AuditLog).filter_by(action=m.AuditAction.candidate_approved).count() == 1
    assert client.post(f"/api/candidates/{cand.id}/approve").status_code == 409  # idempotent guard


def test_reject_keeps_history_and_audits(client, db):
    _login(client, db, m.UserRole.admin)
    cand = _seed_candidate(db)
    r = client.post(f"/api/candidates/{cand.id}/reject")
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    db.refresh(cand)
    assert cand.status == m.CandidateStatus.rejected
    assert db.get(m.Candidate, cand.id) is not None  # retained in history
    assert db.query(m.AuditLog).filter_by(action=m.AuditAction.candidate_rejected).count() == 1


def test_role_enforcement(client, db):
    _login(client, db, m.UserRole.assignee)
    assert client.get("/api/candidates").status_code == 403


def test_unauthenticated(client):
    assert client.get("/api/candidates").status_code == 401
