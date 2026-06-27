"""Admin-invite flow: admin mints a code → bot redeems it → a NEW admin is created."""
from aiwip_api import auth, invite
from aiwip_core import models as m
from aiwip_core.redis_client import get_redis


def _login_admin(client, db, email="admin@x.io"):
    u = m.User(email=email, role=m.UserRole.admin, password_hash=auth.hash_password("pw123456"))
    db.add(u)
    db.flush()
    client.post("/api/auth/login", json={"email": email, "password": "pw123456"})
    return u


def _clear_rl():
    r = get_redis()
    for key in r.scan_iter("tglink:rl:*"):
        r.delete(key)


def test_invite_start_requires_admin(client, db):
    assert client.post("/api/auth/invite/start").status_code == 401


def test_invite_start_then_redeem_creates_new_admin(client, db):
    _login_admin(client, db)
    _clear_rl()
    code = client.post("/api/auth/invite/start").json()["code"]

    before = db.query(m.User).count()
    r = client.post("/api/auth/invite/redeem", json={
        "code": code, "telegram_user_id": 555111, "display_name": "Иван", "telegram_username": "ivan",
    })
    assert r.status_code == 200 and r.json()["status"] == "registered"

    # a brand-new admin User + linked Assignee now exist, bound to the telegram id
    assert db.query(m.User).count() == before + 1
    assignee = db.query(m.Assignee).filter_by(telegram_user_id=555111).one()
    user = db.get(m.User, assignee.user_id)
    assert user.role == m.UserRole.admin
    assert assignee.display_name == "Иван"


def test_invite_code_is_single_use(client, db):
    _login_admin(client, db)
    _clear_rl()
    code = client.post("/api/auth/invite/start").json()["code"]
    assert client.post("/api/auth/invite/redeem", json={"code": code, "telegram_user_id": 1}).status_code == 200
    # second redeem of the same code fails (already consumed)
    assert client.post("/api/auth/invite/redeem", json={"code": code, "telegram_user_id": 2}).status_code == 400


def test_invite_redeem_bad_code(client, db):
    _clear_rl()
    assert client.post("/api/auth/invite/redeem", json={"code": "nope", "telegram_user_id": 9}).status_code == 400


def test_invite_redeem_is_idempotent_for_same_telegram_id(client, db):
    _login_admin(client, db)
    _clear_rl()
    code1 = client.post("/api/auth/invite/start").json()["code"]
    client.post("/api/auth/invite/redeem", json={"code": code1, "telegram_user_id": 777, "display_name": "X"})
    n = db.query(m.User).count()
    # a second invite redeemed by the SAME telegram id logs in, does not duplicate the user
    code2 = client.post("/api/auth/invite/start").json()["code"]
    r = client.post("/api/auth/invite/redeem", json={"code": code2, "telegram_user_id": 777})
    assert r.status_code == 200
    assert db.query(m.User).count() == n  # no duplicate


def test_invite_redeem_rate_limited(client, db):
    _login_admin(client, db)
    _clear_rl()
    # exhaust the per-IP window with bad codes, then a good code is throttled too
    for _ in range(6):
        client.post("/api/auth/invite/redeem", json={"code": "x", "telegram_user_id": 4242})
    code = client.post("/api/auth/invite/start").json()["code"]
    assert client.post("/api/auth/invite/redeem", json={"code": code, "telegram_user_id": 4242}).status_code == 429
