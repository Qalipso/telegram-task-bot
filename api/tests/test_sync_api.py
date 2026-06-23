"""Stage 4 — admin sync API (queue enqueue mocked; role enforcement real)."""
from aiwip_api import auth
from aiwip_core import models as m


def _login(client, db, role):
    email = f"{role.value}@x.io"
    db.add(m.User(email=email, role=role, password_hash=auth.hash_password("pw123456")))
    db.flush()
    client.post("/api/auth/login", json={"email": email, "password": "pw123456"})


def test_post_run_enqueues_for_admin(client, db, monkeypatch):
    calls = []
    monkeypatch.setattr("aiwip_core.queue.enqueue_sync", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr("aiwip_core.queue.queue_length", lambda: 1)
    _login(client, db, m.UserRole.admin)
    r = client.post("/api/sync/run", json={"chat_id": -100123})
    assert r.status_code == 202, r.text
    assert r.json()["chat_id"] == -100123
    assert len(calls) == 1


def test_post_run_requires_admin(client, db):
    _login(client, db, m.UserRole.assignee)
    assert client.post("/api/sync/run", json={"chat_id": 1}).status_code == 403


def test_post_run_unauthenticated(client):
    assert client.post("/api/sync/run", json={"chat_id": 1}).status_code == 401


def test_status_and_history_for_admin(client, db, monkeypatch):
    monkeypatch.setattr("aiwip_core.queue.queue_length", lambda: 0)
    _login(client, db, m.UserRole.admin)
    db.add(m.SyncRun(trigger_type=m.SyncTriggerType.manual, status=m.SyncRunStatus.success, messages_read=5, messages_saved=5))
    db.flush()
    status_resp = client.get("/api/sync/status")
    assert status_resp.status_code == 200 and "latest_run" in status_resp.json()
    history = client.get("/api/sync/history")
    assert history.status_code == 200 and isinstance(history.json(), list) and len(history.json()) >= 1
