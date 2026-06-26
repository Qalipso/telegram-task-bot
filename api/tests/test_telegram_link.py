"""Phase 2 — Telegram account-linking: link codes + rate limit + redeem endpoint (spec §6.4).

Security-critical. Redis is REAL and shared (conftest forces localhost) and is NOT rolled back,
so every test uses unique codes / ids and cleans up its own keys; an autouse fixture resets the
per-IP redeem counter so the live limiter does not bleed across tests.
"""
import uuid
from pathlib import Path

import pytest

from aiwip_api import auth, telegram_link as tl
from aiwip_core import models as mdl


@pytest.fixture(autouse=True)
def _reset_rate_limit_counters():
    """Each test starts with clean rate-limit counters (shared real Redis is NOT rolled back, and
    happy-path tests reuse fixed telegram_user_ids, so per-tg counters would otherwise accumulate
    across repeated suite runs inside the 300s window and spuriously trip 429)."""
    r = tl.get_redis()

    def _clear():
        keys = list(r.scan_iter(match="tglink:rl:*"))
        if keys:
            r.delete(*keys)

    _clear()
    yield
    _clear()


def _make_user(db, email, role):
    u = mdl.User(email=email, role=role, password_hash=auth.hash_password("pw123456"))
    db.add(u)
    db.flush()
    return u


def _admin_with_assignee(db, email="admin2@x.io"):
    u = _make_user(db, email, mdl.UserRole.admin)
    a = mdl.Assignee(display_name="Admin Two", user_id=u.id, is_active=True)
    db.add(a)
    db.flush()
    return u, a


# --------------------------------------------------------------------------- primitives
def test_module_exposes_contract():
    # Redis prefixes are NEW and MUST be distinct from the session prefix.
    assert tl.LINK_CODE_PREFIX == "tglink:"
    assert tl.LINK_CODE_TTL_SECONDS == 300            # ~5 min
    assert tl.RATE_LIMIT_TGUSER_PREFIX == "tglink:rl:tg:"
    assert tl.RATE_LIMIT_IP_PREFIX == "tglink:rl:ip:"
    assert tl.RATE_LIMIT_MAX_ATTEMPTS == 5
    assert tl.RATE_LIMIT_WINDOW_SECONDS == 300
    for name in ("issue_link_code", "redeem_link_code", "check_and_increment_rate_limit"):
        assert callable(getattr(tl, name))


def test_issue_then_redeem_returns_user_id_once():
    code = tl.issue_link_code(4242)
    try:
        assert tl.redeem_link_code(code) == 4242   # first redeem returns the bound user id
        assert tl.redeem_link_code(code) is None    # second redeem: already consumed
    finally:
        tl.get_redis().delete(tl.LINK_CODE_PREFIX + code)


def test_redeem_unknown_code_returns_none():
    assert tl.redeem_link_code("definitely-not-a-real-code") is None


def test_rate_limit_allows_then_trips():
    suffix = uuid.uuid4().hex  # unique key so this test never collides with another
    prefix = tl.RATE_LIMIT_TGUSER_PREFIX
    try:
        for _ in range(tl.RATE_LIMIT_MAX_ATTEMPTS):
            assert tl.check_and_increment_rate_limit(suffix, prefix) is True
        assert tl.check_and_increment_rate_limit(suffix, prefix) is False
    finally:
        tl.get_redis().delete(prefix + suffix)


# --------------------------------------------------------------------------- start endpoint
def test_start_requires_authentication(client):
    assert client.post("/api/auth/telegram-link/start").status_code == 401


def test_start_rejects_non_admin(client, db):
    _make_user(db, "ass@x.io", mdl.UserRole.assignee)
    client.post("/api/auth/login", json={"email": "ass@x.io", "password": "pw123456"})
    assert client.post("/api/auth/telegram-link/start").status_code == 403


def test_start_returns_code_for_admin(client, db):
    _make_user(db, "admin@x.io", mdl.UserRole.admin)
    client.post("/api/auth/login", json={"email": "admin@x.io", "password": "pw123456"})
    r = client.post("/api/auth/telegram-link/start")
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body["code"], str) and len(body["code"]) >= 20
    assert body["expires_in_seconds"] == tl.LINK_CODE_TTL_SECONDS
    tl.get_redis().delete(tl.LINK_CODE_PREFIX + body["code"])


# --------------------------------------------------------------------------- redeem endpoint
def test_redeem_links_telegram_id_and_mints_session(client, db):
    user, assignee = _admin_with_assignee(db)
    code = tl.issue_link_code(user.id)
    r = client.post("/api/auth/telegram/redeem", json={"code": code, "telegram_user_id": 987654321})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "linked"
    db.refresh(assignee)
    assert assignee.telegram_user_id == 987654321
    me = client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["email"] == "admin2@x.io"


def test_redeem_is_single_use(client, db):
    user, _ = _admin_with_assignee(db, email="admin3@x.io")
    code = tl.issue_link_code(user.id)
    first = client.post("/api/auth/telegram/redeem", json={"code": code, "telegram_user_id": 111})
    assert first.status_code == 200, first.text
    second = client.post("/api/auth/telegram/redeem", json={"code": code, "telegram_user_id": 111})
    assert second.status_code == 400  # already consumed -> "Invalid or expired link code"


def test_redeem_refuses_user_without_linked_assignee(client, db):
    user = _make_user(db, "admin4@x.io", mdl.UserRole.admin)  # NO assignee row at all
    code = tl.issue_link_code(user.id)
    r = client.post("/api/auth/telegram/redeem", json={"code": code, "telegram_user_id": 222})
    assert r.status_code == 400
    assert "assignee" in r.json()["detail"].lower()
    assert client.get("/api/auth/me").status_code == 401  # no session minted on refusal


def test_redeem_does_not_autocreate_user(client, db):
    before = db.query(mdl.User).count()
    code = tl.issue_link_code(999999)  # bound to a user id that does not exist
    r = client.post("/api/auth/telegram/redeem", json={"code": code, "telegram_user_id": 333})
    assert r.status_code == 400
    assert db.query(mdl.User).count() == before  # no user created
    assert db.query(mdl.Assignee).count() == 0   # no assignee created


def test_redeem_identity_comes_from_code_not_body(client, db):
    user_a, assignee_a = _admin_with_assignee(db, email="alice@x.io")
    user_b, assignee_b = _admin_with_assignee(db, email="bob@x.io")
    code_a = tl.issue_link_code(user_a.id)  # code bound to Alice
    r = client.post("/api/auth/telegram/redeem", json={"code": code_a, "telegram_user_id": 555})
    assert r.status_code == 200, r.text
    db.refresh(assignee_a)
    db.refresh(assignee_b)
    assert assignee_a.telegram_user_id == 555   # written to the code's owner
    assert assignee_b.telegram_user_id is None  # Bob untouched
    assert client.get("/api/auth/me").json()["email"] == "alice@x.io"


def test_redeem_rate_limit_trips_per_telegram_user(client, db):
    tg_id = 70000000 + int(uuid.uuid4().int % 1000)
    tg_key = tl.RATE_LIMIT_TGUSER_PREFIX + str(tg_id)
    ip_key = tl.RATE_LIMIT_IP_PREFIX + "testclient"
    r = tl.get_redis()
    r.delete(tg_key, ip_key)
    try:
        last_status = None
        for _ in range(tl.RATE_LIMIT_MAX_ATTEMPTS + 1):
            resp = client.post(
                "/api/auth/telegram/redeem",
                json={"code": "bad-code-" + uuid.uuid4().hex, "telegram_user_id": tg_id},
            )
            last_status = resp.status_code
        assert last_status == 429  # final attempt is rate-limited, not 400
    finally:
        r.delete(tg_key, ip_key)


# --------------------------------------------------------------------------- cookie + env
def test_login_cookie_is_secure(client, db):
    _make_user(db, "secureadmin@x.io", mdl.UserRole.admin)
    r = client.post("/api/auth/login", json={"email": "secureadmin@x.io", "password": "pw123456"})
    assert r.status_code == 200, r.text
    set_cookie = r.headers.get("set-cookie", "")
    assert "secure" in set_cookie.lower()    # spec §6.4: secure cookie
    assert "httponly" in set_cookie.lower()  # unchanged existing guarantee


def test_env_example_documents_bot_token():
    env = Path(__file__).resolve().parents[2] / ".env.example"
    assert "TELEGRAM_BOT_TOKEN" in env.read_text(encoding="utf-8")
