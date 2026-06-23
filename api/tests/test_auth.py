"""Stage 3 — authentication, roles, and admin-only access (real Postgres + Redis)."""
from aiwip_api import auth
from aiwip_core import models as m


def _make_user(db, email, password, role):
    u = m.User(email=email, role=role, password_hash=auth.hash_password(password))
    db.add(u)
    db.flush()
    return u


def test_password_hash_roundtrip():
    h = auth.hash_password("s3cret-pw")
    assert h != "s3cret-pw"
    assert auth.verify_password("s3cret-pw", h)
    assert not auth.verify_password("wrong", h)


def test_login_me_logout(client, db):
    _make_user(db, "admin@x.io", "pw123456", m.UserRole.admin)
    r = client.post("/api/auth/login", json={"email": "admin@x.io", "password": "pw123456"})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "admin"
    me = client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["email"] == "admin@x.io"
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_login_wrong_password(client, db):
    _make_user(db, "a@x.io", "rightpw", m.UserRole.admin)
    assert client.post("/api/auth/login", json={"email": "a@x.io", "password": "nope"}).status_code == 401


def test_login_unknown_email(client):
    assert client.post("/api/auth/login", json={"email": "ghost@x.io", "password": "x"}).status_code == 401


def test_me_requires_auth(client):
    assert client.get("/api/auth/me").status_code == 401


def test_admin_can_list_users(client, db):
    _make_user(db, "admin@x.io", "pw123456", m.UserRole.admin)
    client.post("/api/auth/login", json={"email": "admin@x.io", "password": "pw123456"})
    r = client.get("/api/users")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_assignee_cannot_list_users(client, db):
    _make_user(db, "ass@x.io", "pw123456", m.UserRole.assignee)
    client.post("/api/auth/login", json={"email": "ass@x.io", "password": "pw123456"})
    assert client.get("/api/users").status_code == 403


def test_unauthenticated_cannot_list_users(client):
    assert client.get("/api/users").status_code == 401


def test_admin_can_create_user(client, db):
    _make_user(db, "admin@x.io", "pw123456", m.UserRole.admin)
    client.post("/api/auth/login", json={"email": "admin@x.io", "password": "pw123456"})
    r = client.post(
        "/api/users",
        json={"email": "new@x.io", "password": "pw234567", "role": "assignee", "display_name": "New"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["email"] == "new@x.io"


def test_assignee_cannot_create_user(client, db):
    _make_user(db, "ass@x.io", "pw123456", m.UserRole.assignee)
    client.post("/api/auth/login", json={"email": "ass@x.io", "password": "pw123456"})
    r = client.post("/api/users", json={"email": "x@x.io", "password": "pw234567", "role": "assignee"})
    assert r.status_code == 403


def test_seed_admin_idempotent(db):
    from aiwip_api.seed import ensure_admin

    u1 = ensure_admin(db, "boss@x.io", "pw123456", "Boss")
    u2 = ensure_admin(db, "boss@x.io", "pw123456", "Boss")
    assert u1.id == u2.id
    assert u1.role == m.UserRole.admin
