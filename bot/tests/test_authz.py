"""Phase 4 — per-callback tapper authorization (§6.4). Real Postgres via the root `db` fixture."""
from aiwip_bot import authz
from aiwip_core import models as m


def _admin_user(db):
    u = m.User(email="admin@aiwip.local", role=m.UserRole.admin)
    db.add(u)
    db.flush()
    return u


def _assignee_user(db):
    u = m.User(email="worker@aiwip.local", role=m.UserRole.assignee)
    db.add(u)
    db.flush()
    return u


def test_linked_admin_is_authorized(db):
    admin = _admin_user(db)
    db.add(m.Assignee(display_name="Boss", telegram_user_id=111, user_id=admin.id, is_active=True))
    db.flush()
    result = authz.authorize_tapper(db, telegram_user_id=111)
    assert result.allowed is True
    assert result.user_id == admin.id


def test_unlinked_telegram_user_is_denied(db):
    db.add(m.Assignee(display_name="Ghost", telegram_user_id=222, user_id=None, is_active=True))
    db.flush()
    result = authz.authorize_tapper(db, telegram_user_id=222)
    assert result.allowed is False


def test_unknown_telegram_user_is_denied(db):
    result = authz.authorize_tapper(db, telegram_user_id=999999)
    assert result.allowed is False
    assert result.user_id is None


def test_linked_non_admin_is_denied(db):
    worker = _assignee_user(db)
    db.add(m.Assignee(display_name="Worker", telegram_user_id=333, user_id=worker.id, is_active=True))
    db.flush()
    result = authz.authorize_tapper(db, telegram_user_id=333)
    assert result.allowed is False
    assert result.user_id == worker.id  # identified, but not permitted


def test_denied_result_has_user_facing_reason(db):
    result = authz.authorize_tapper(db, telegram_user_id=424242)
    assert result.reason  # non-empty "ask an admin"-style message
