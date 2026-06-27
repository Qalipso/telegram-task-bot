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
    msg = detail["messages"][0]
    assert msg["text"] == "do x" and msg["role"] == "primary" and msg["external_message_id"] == 1


def test_edit_assigns_responsible_and_syncs_missing_fields(client, db):
    _login(client, db, m.UserRole.admin)
    cand = _seed_candidate(db)  # seeded with Bob assigned, missing_fields=[]
    bob = db.query(m.Assignee).first()

    # clear the responsible person -> assignee re-flagged missing
    assert client.patch(f"/api/candidates/{cand.id}", json={"assignee_ids": []}).status_code == 200
    detail = client.get(f"/api/candidates/{cand.id}").json()
    assert detail["assignees"] == [] and "assignee" in detail["candidate"]["missing_fields"]

    # assign a responsible person -> flag cleared, name available
    client.patch(f"/api/candidates/{cand.id}", json={"assignee_ids": [bob.id]})
    detail = client.get(f"/api/candidates/{cand.id}").json()
    assert len(detail["assignees"]) == 1 and detail["assignees"][0]["assignee_id"] == bob.id
    assert detail["assignees"][0]["display_name"] == "Bob"
    assert "assignee" not in (detail["candidate"]["missing_fields"] or [])


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


def test_candidate_out_exposes_assignee_signal_and_confidences(client, db):
    """§6.1B + §6.2: the detail payload carries the bot's branching signals — assignee_count,
    assignee_ambiguous, unresolved_mentions, and the four per-field confidences."""
    _login(client, db, m.UserRole.admin)
    chat = m.Chat(connector_type=m.ConnectorType.telegram, external_chat_id=950)
    db.add(chat)
    db.flush()
    cand = m.Candidate(
        candidate_type=m.CandidateType.task, title="Do Y", summary="s",
        status=m.CandidateStatus.needs_review, task_confidence=0.95,
        context_confidence=0.8, assignee_confidence=0.7, priority_confidence=0.6,
        due_date_confidence=0.5, missing_fields=["assignee"], unresolved_mentions=["Сашка"],
    )
    db.add(cand)
    db.flush()
    a1 = m.Assignee(display_name="Саша", telegram_username="sasha1")
    a2 = m.Assignee(display_name="Александр", telegram_username="sasha2")
    db.add(a1)
    db.add(a2)
    db.flush()
    db.add(m.CandidateAssignee(candidate_id=cand.id, assignee_id=a1.id, is_primary=True))
    db.add(m.CandidateAssignee(candidate_id=cand.id, assignee_id=a2.id, is_primary=False))
    db.flush()

    out = client.get(f"/api/candidates/{cand.id}").json()["candidate"]
    assert out["assignee_count"] == 2
    assert out["assignee_ambiguous"] is True  # 2+ linked OR unresolved mentions present
    assert out["unresolved_mentions"] == ["Сашка"]
    assert out["assignee_confidence"] == 0.7
    assert out["priority_confidence"] == 0.6
    assert out["due_date_confidence"] == 0.5
    assert out["context_confidence"] == 0.8


def test_patch_rejects_nonexistent_assignee_id(client, db):
    """§6.1D: a stale/forged assignee id must be rejected (422), not silently linked."""
    _login(client, db, m.UserRole.admin)
    cand = _seed_candidate(db)  # seeded with Bob assigned
    r = client.patch(f"/api/candidates/{cand.id}", json={"assignee_ids": [999999]})
    assert r.status_code == 422, r.text


def test_patch_rejects_inactive_assignee_id(client, db):
    """§6.1D: an inactive assignee must not be assignable via the bot/admin PATCH."""
    _login(client, db, m.UserRole.admin)
    cand = _seed_candidate(db)
    ghost = m.Assignee(display_name="Ghost", telegram_username="ghost", is_active=False)
    db.add(ghost)
    db.flush()
    r = client.patch(f"/api/candidates/{cand.id}", json={"assignee_ids": [ghost.id]})
    assert r.status_code == 422, r.text


def test_patch_clears_missing_field_when_set(client, db):
    """Setting due_date via PATCH must drop 'due_date' from missing_fields (card stops nagging)."""
    from aiwip_api import auth as _auth
    import datetime as _dt
    u = m.User(email="ed@x.io", role=m.UserRole.admin, password_hash=_auth.hash_password("pw123456"))
    db.add(u); db.flush()
    client.post("/api/auth/login", json={"email": "ed@x.io", "password": "pw123456"})
    c = m.Candidate(candidate_type=m.CandidateType.task, title="t", status=m.CandidateStatus.needs_review,
                    missing_fields=["due_date", "assignee"])
    db.add(c); db.flush()
    r = client.patch(f"/api/candidates/{c.id}", json={"due_date": "2026-06-29T00:00:00Z"})
    assert r.status_code == 200
    out = r.json()
    assert "due_date" not in (out["missing_fields"] or [])
    assert "assignee" in (out["missing_fields"] or [])  # untouched field stays
