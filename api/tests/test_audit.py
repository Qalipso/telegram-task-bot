"""Stage 11 — audit query API + actor tracking."""
from aiwip_api import auth
from aiwip_core import models as m


def _login(client, db, role, email):
    db.add(m.User(email=email, role=role, password_hash=auth.hash_password("pw123456")))
    db.flush()
    client.post("/api/auth/login", json={"email": email, "password": "pw123456"})


def test_action_recorded_and_queryable_with_actor(client, db):
    _login(client, db, m.UserRole.admin, "admin@x.io")
    client.post("/api/assignees", json={"display_name": "Bob", "telegram_username": "bob"})
    entries = client.get("/api/audit?action=assignee_created").json()
    assert len(entries) >= 1
    assert entries[0]["entity_type"] == "assignee"
    assert entries[0]["actor_user_id"] is not None  # actor tracked


def test_filter_by_entity_type(client, db):
    _login(client, db, m.UserRole.admin, "admin@x.io")
    client.post("/api/assignees", json={"display_name": "X"})
    res = client.get("/api/audit?entity_type=assignee").json()
    assert len(res) >= 1 and all(x["entity_type"] == "assignee" for x in res)


def test_audit_admin_only(client, db):
    _login(client, db, m.UserRole.assignee, "ass@x.io")
    assert client.get("/api/audit").status_code == 403


def test_audit_unauthenticated(client):
    assert client.get("/api/audit").status_code == 401
