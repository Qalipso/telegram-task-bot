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


def test_unauthenticated(client):
    assert client.get("/api/work-items").status_code == 401
