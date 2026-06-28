"""Stage 10 — WorkItem list/board/status/tags + assignee visibility."""
from aiwip_api import auth
from aiwip_core import models as m


def _login_user(client, db, role, email):
    u = m.User(email=email, role=role, password_hash=auth.hash_password("pw123456"))
    db.add(u)
    db.flush()
    client.post("/api/auth/login", json={"email": email, "password": "pw123456"})
    return u


def _work_item(db, status=m.WorkItemStatus.inbox, title="WI"):
    cand = m.Candidate(candidate_type=m.CandidateType.task, title=title, status=m.CandidateStatus.approved)
    db.add(cand)
    db.flush()
    wi = m.WorkItem(source_candidate_id=cand.id, type=m.WorkItemType.task, title=title, status=status)
    db.add(wi)
    db.flush()
    return wi


def test_board_groups_by_status(client, db):
    _login_user(client, db, m.UserRole.admin, "admin@x.io")
    _work_item(db, m.WorkItemStatus.inbox, "A")
    _work_item(db, m.WorkItemStatus.in_progress, "B")
    cols = client.get("/api/work-items/board").json()["columns"]
    assert set(cols.keys()) == {s.value for s in m.WorkItemStatus}  # all 9 columns present
    assert len(cols["inbox"]) == 1 and len(cols["in_progress"]) == 1


def test_status_change_and_audit(client, db):
    _login_user(client, db, m.UserRole.admin, "admin@x.io")
    wi = _work_item(db, m.WorkItemStatus.inbox)
    r = client.post(f"/api/work-items/{wi.id}/status", json={"status": "in_progress"})
    assert r.status_code == 200 and r.json()["status"] == "in_progress"
    aud = db.query(m.AuditLog).filter_by(action=m.AuditAction.work_item_status_changed).all()
    assert len(aud) == 1 and aud[0].before_value["status"] == "inbox" and aud[0].after_value["status"] == "in_progress"


def test_cancelled_is_preserved_not_deleted(client, db):
    _login_user(client, db, m.UserRole.admin, "admin@x.io")
    wi = _work_item(db)
    client.post(f"/api/work-items/{wi.id}/status", json={"status": "cancelled"})
    ids = [w["id"] for w in client.get("/api/work-items?status=cancelled").json()]
    assert wi.id in ids
    db.refresh(wi)
    assert wi.status == m.WorkItemStatus.cancelled


def test_tag_relation(client, db):
    _login_user(client, db, m.UserRole.admin, "admin@x.io")
    wi = _work_item(db)
    label = client.post("/api/labels", json={"name": "backend", "color": "#00f"}).json()
    assert client.post(f"/api/work-items/{wi.id}/labels", json={"label_id": label["id"]}).status_code == 201
    detail = client.get(f"/api/work-items/{wi.id}").json()
    assert [lbl["name"] for lbl in detail["labels"]] == ["backend"]


def test_assignee_visibility_and_status(client, db):
    user = _login_user(client, db, m.UserRole.assignee, "ass@x.io")
    a = m.Assignee(user_id=user.id, display_name="A", telegram_username="a")
    db.add(a)
    db.flush()
    mine = _work_item(db, title="mine")
    db.add(m.WorkItemAssignee(work_item_id=mine.id, assignee_id=a.id, is_primary=True))
    other = _work_item(db, title="other")
    db.flush()

    ids = [w["id"] for w in client.get("/api/work-items").json()]
    assert mine.id in ids and other.id not in ids
    assert client.get(f"/api/work-items/{other.id}").status_code == 404
    assert client.post(f"/api/work-items/{mine.id}/status", json={"status": "in_progress"}).status_code == 200
    assert client.post(f"/api/work-items/{other.id}/status", json={"status": "done"}).status_code == 404


def test_edit_work_item_and_audit(client, db):
    _login_user(client, db, m.UserRole.admin, "admin@x.io")
    wi = _work_item(db, title="old title")
    r = client.patch(
        f"/api/work-items/{wi.id}",
        json={
            "title": "new title",
            "summary": "a summary",
            "priority": "high",
            "due_date": "2026-07-01T00:00:00Z",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"] == "new title"
    assert body["summary"] == "a summary"
    assert body["priority"] == "high"
    db.refresh(wi)
    assert wi.title == "new title" and wi.priority == m.Priority.high
    aud = db.query(m.AuditLog).filter_by(action=m.AuditAction.work_item_edited).all()
    assert len(aud) == 1
    assert aud[0].before_value["title"] == "old title"
    assert aud[0].after_value["title"] == "new title"


def test_edit_work_item_partial_leaves_other_fields(client, db):
    _login_user(client, db, m.UserRole.admin, "admin@x.io")
    wi = _work_item(db, title="keep me")
    r = client.patch(f"/api/work-items/{wi.id}", json={"summary": "only summary"})
    assert r.status_code == 200
    db.refresh(wi)
    assert wi.title == "keep me"  # untouched
    assert wi.summary == "only summary"


def test_edit_work_item_clear_nullable_field(client, db):
    _login_user(client, db, m.UserRole.admin, "admin@x.io")
    wi = _work_item(db, title="t")
    wi.priority = m.Priority.high
    db.flush()
    r = client.patch(f"/api/work-items/{wi.id}", json={"priority": None})
    assert r.status_code == 200
    db.refresh(wi)
    assert wi.priority is None


def test_edit_work_item_requires_admin(client, db):
    user = _login_user(client, db, m.UserRole.assignee, "ass@x.io")
    a = m.Assignee(user_id=user.id, display_name="A", telegram_username="a")
    db.add(a)
    db.flush()
    mine = _work_item(db, title="mine")
    db.add(m.WorkItemAssignee(work_item_id=mine.id, assignee_id=a.id, is_primary=True))
    db.flush()
    # Assignees may transition status (existing behaviour) but NOT edit content fields.
    assert client.patch(f"/api/work-items/{mine.id}", json={"title": "x"}).status_code == 403


def test_edit_work_item_404(client, db):
    _login_user(client, db, m.UserRole.admin, "admin@x.io")
    assert client.patch("/api/work-items/99999", json={"title": "x"}).status_code == 404


def test_edit_work_item_rejects_overlong_title(client, db):
    _login_user(client, db, m.UserRole.admin, "admin@x.io")
    wi = _work_item(db, title="t")
    r = client.patch(f"/api/work-items/{wi.id}", json={"title": "x" * 513})
    assert r.status_code == 422  # clean validation error, not a 500 truncation


def _assignee(db, name="A", username="a", active=True):
    a = m.Assignee(display_name=name, telegram_username=username, is_active=active)
    db.add(a)
    db.flush()
    return a


def _assignee_ids(client, wi_id):
    detail = client.get(f"/api/work-items/{wi_id}").json()
    return [a["assignee_id"] for a in detail["assignees"]]


def test_reassign_replaces_assignees_happy_path(client, db):
    _login_user(client, db, m.UserRole.admin, "admin@x.io")
    wi = _work_item(db)
    a1, a2, a3 = _assignee(db, "One", "one"), _assignee(db, "Two", "two"), _assignee(db, "Three", "three")
    db.add(m.WorkItemAssignee(work_item_id=wi.id, assignee_id=a1.id, is_primary=True))
    db.flush()
    r = client.put(f"/api/work-items/{wi.id}/assignees", json={"assignee_ids": [a2.id, a3.id]})
    assert r.status_code == 200, r.text
    assert set(_assignee_ids(client, wi.id)) == {a2.id, a3.id}  # a1 gone


def test_reassign_writes_audit_row(client, db):
    _login_user(client, db, m.UserRole.admin, "admin@x.io")
    wi = _work_item(db)
    a1, a2 = _assignee(db, "One", "one"), _assignee(db, "Two", "two")
    db.add(m.WorkItemAssignee(work_item_id=wi.id, assignee_id=a1.id, is_primary=True))
    db.flush()
    client.put(f"/api/work-items/{wi.id}/assignees", json={"assignee_ids": [a2.id]})
    aud = db.query(m.AuditLog).filter_by(action=m.AuditAction.work_item_reassigned, entity_id=wi.id).all()
    assert len(aud) == 1
    assert aud[0].before_value["assignee_ids"] == [a1.id]
    assert aud[0].after_value["assignee_ids"] == [a2.id]


def test_reassign_first_id_is_primary(client, db):
    _login_user(client, db, m.UserRole.admin, "admin@x.io")
    wi = _work_item(db)
    a1, a2 = _assignee(db, "One", "one"), _assignee(db, "Two", "two")
    client.put(f"/api/work-items/{wi.id}/assignees", json={"assignee_ids": [a2.id, a1.id]})
    rows = {wa.assignee_id: wa.is_primary
            for wa in db.query(m.WorkItemAssignee).filter_by(work_item_id=wi.id).all()}
    assert rows == {a2.id: True, a1.id: False}


def test_reassign_empty_list_clears(client, db):
    _login_user(client, db, m.UserRole.admin, "admin@x.io")
    wi = _work_item(db)
    a1 = _assignee(db, "One", "one")
    db.add(m.WorkItemAssignee(work_item_id=wi.id, assignee_id=a1.id, is_primary=True))
    db.flush()
    r = client.put(f"/api/work-items/{wi.id}/assignees", json={"assignee_ids": []})
    assert r.status_code == 200
    assert _assignee_ids(client, wi.id) == []


def test_reassign_rejects_unknown_assignee_id(client, db):
    _login_user(client, db, m.UserRole.admin, "admin@x.io")
    wi = _work_item(db)
    a1 = _assignee(db, "One", "one")
    db.add(m.WorkItemAssignee(work_item_id=wi.id, assignee_id=a1.id, is_primary=True))
    db.flush()
    r = client.put(f"/api/work-items/{wi.id}/assignees", json={"assignee_ids": [99999]})
    assert r.status_code == 422
    assert _assignee_ids(client, wi.id) == [a1.id]  # no partial mutation


def test_reassign_rejects_inactive_assignee_id(client, db):
    _login_user(client, db, m.UserRole.admin, "admin@x.io")
    wi = _work_item(db)
    inactive = _assignee(db, "Gone", "gone", active=False)
    r = client.put(f"/api/work-items/{wi.id}/assignees", json={"assignee_ids": [inactive.id]})
    assert r.status_code == 422


def test_reassign_requires_admin(client, db):
    user = _login_user(client, db, m.UserRole.assignee, "ass@x.io")
    a = m.Assignee(user_id=user.id, display_name="A", telegram_username="a")
    db.add(a)
    db.flush()
    mine = _work_item(db, title="mine")
    db.add(m.WorkItemAssignee(work_item_id=mine.id, assignee_id=a.id, is_primary=True))
    db.flush()
    assert client.put(f"/api/work-items/{mine.id}/assignees", json={"assignee_ids": [a.id]}).status_code == 403


def test_reassign_rejects_duplicate_ids(client, db):
    _login_user(client, db, m.UserRole.admin, "admin@x.io")
    wi = _work_item(db)
    a1 = _assignee(db, "One", "one")
    r = client.put(f"/api/work-items/{wi.id}/assignees", json={"assignee_ids": [a1.id, a1.id]})
    assert r.status_code == 422  # clean validation error, not a 500 unique-constraint violation


def test_reassign_unknown_work_item_404(client, db):
    _login_user(client, db, m.UserRole.admin, "admin@x.io")
    assert client.put("/api/work-items/99999/assignees", json={"assignee_ids": []}).status_code == 404


def test_unauthenticated(client):
    assert client.get("/api/work-items").status_code == 401
