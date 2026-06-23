"""Stage 6 — assignee CRUD API (admin-only)."""
from aiwip_api import auth
from aiwip_core import models as m


def _login(client, db, role):
    email = f"{role.value}@x.io"
    db.add(m.User(email=email, role=role, password_hash=auth.hash_password("pw123456")))
    db.flush()
    client.post("/api/auth/login", json={"email": email, "password": "pw123456"})


def test_admin_create_list_edit_deactivate(client, db):
    _login(client, db, m.UserRole.admin)

    created = client.post(
        "/api/assignees",
        json={"display_name": "Bob", "telegram_username": "bob", "aliases": ["Bobby", "Robert"]},
    )
    assert created.status_code == 201, created.text
    aid = created.json()["id"]
    assert created.json()["is_active"] is True
    assert created.json()["aliases"] == ["Bobby", "Robert"]

    listed = client.get("/api/assignees")
    assert listed.status_code == 200 and len(listed.json()) == 1

    edited = client.patch(f"/api/assignees/{aid}", json={"display_name": "Bob Smith"})
    assert edited.status_code == 200 and edited.json()["display_name"] == "Bob Smith"

    deactivated = client.patch(f"/api/assignees/{aid}", json={"is_active": False})
    assert deactivated.status_code == 200 and deactivated.json()["is_active"] is False
    assert client.get("/api/assignees?active=true").json() == []
    assert len(client.get("/api/assignees?active=false").json()) == 1


def test_assignee_role_cannot_manage(client, db):
    _login(client, db, m.UserRole.assignee)
    assert client.get("/api/assignees").status_code == 403
    assert client.post("/api/assignees", json={"display_name": "X"}).status_code == 403


def test_unauthenticated_blocked(client):
    assert client.get("/api/assignees").status_code == 401


def test_patch_missing_returns_404(client, db):
    _login(client, db, m.UserRole.admin)
    assert client.patch("/api/assignees/9999", json={"display_name": "x"}).status_code == 404
