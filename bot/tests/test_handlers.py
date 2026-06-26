"""Phase 4 — callback handlers (approve/reject/assign/who/pick/edit). Real DB authz; fake ApiClient."""
import pytest

from aiwip_bot import handlers
from aiwip_core import models as m


class FakeApiClient:
    """Records calls and returns canned candidate JSON. The bot NEVER calls /approve itself
    except through handle_approve, which a human tap triggers — this fake lets us assert that."""

    def __init__(self, candidate: dict):
        self._candidate = candidate
        self.approved: list[int] = []
        self.rejected: list[int] = []
        self.patched: list[tuple[int, dict]] = []

    def get_candidate(self, candidate_id: int) -> dict:
        return {"candidate": dict(self._candidate, id=candidate_id), "assignees": [], "messages": []}

    def approve_candidate(self, candidate_id: int) -> dict:
        self.approved.append(candidate_id)
        return {"id": 1, "source_candidate_id": candidate_id}

    def reject_candidate(self, candidate_id: int) -> dict:
        self.rejected.append(candidate_id)
        return dict(self._candidate, id=candidate_id, status="rejected")

    def patch_candidate(self, candidate_id: int, payload: dict) -> dict:
        self.patched.append((candidate_id, payload))
        return dict(self._candidate, id=candidate_id, status="edited")

    def list_assignees(self, active: bool = True):
        return [{"id": 10, "display_name": "Alice"}, {"id": 11, "display_name": "Bob"}]


def _admin(db, tg_id=111):
    u = m.User(email=f"admin{tg_id}@aiwip.local", role=m.UserRole.admin)
    db.add(u)
    db.flush()
    db.add(m.Assignee(display_name="A", telegram_user_id=tg_id, user_id=u.id, is_active=True))
    db.flush()
    return u


_READY = {
    "id": 0, "candidate_type": "task", "title": "T", "summary": "S",
    "priority": "high", "due_date": None, "status": "new",
    "task_confidence": 0.95, "missing_fields": [], "assignee_count": 1,
    "assignee_ambiguous": False, "unresolved_mentions": None,
}


def test_parse_callback_round_trips():
    from aiwip_bot import cards
    action, cid = handlers.parse_callback(cards.encode_callback("approve", 42))
    assert action == "approve"
    assert cid == 42


def test_parse_callback_rejects_garbage():
    with pytest.raises(ValueError):
        handlers.parse_callback("not-a-valid-payload")


def test_approve_denied_for_unlinked_tapper(db):
    api = FakeApiClient(_READY)
    res = handlers.handle_approve(db, api, telegram_user_id=777, candidate_id=5)
    assert res.did_act is False
    assert api.approved == []          # the bot did NOT call /approve
    assert "admin" in res.text.lower()


def test_approve_denied_for_non_admin(db):
    worker = m.User(email="w@aiwip.local", role=m.UserRole.assignee)
    db.add(worker)
    db.flush()
    db.add(m.Assignee(display_name="W", telegram_user_id=555, user_id=worker.id, is_active=True))
    db.flush()
    api = FakeApiClient(_READY)
    res = handlers.handle_approve(db, api, telegram_user_id=555, candidate_id=5)
    assert res.did_act is False
    assert api.approved == []


def test_approve_by_admin_calls_endpoint(db):
    _admin(db, tg_id=111)
    api = FakeApiClient(_READY)
    res = handlers.handle_approve(db, api, telegram_user_id=111, candidate_id=5)
    assert res.did_act is True
    assert api.approved == [5]


def test_replayed_approve_on_already_approved_is_noop(db):
    _admin(db, tg_id=222)
    api = FakeApiClient(dict(_READY, status="approved"))  # server says it's already approved
    res = handlers.handle_approve(db, api, telegram_user_id=222, candidate_id=5)
    assert res.did_act is False
    assert api.approved == []          # re-fetch saw approved -> no second /approve call
    assert "already" in res.text.lower()


def test_reject_by_admin_calls_endpoint(db):
    _admin(db, tg_id=333)
    api = FakeApiClient(_READY)
    res = handlers.handle_reject(db, api, telegram_user_id=333, candidate_id=5)
    assert res.did_act is True
    assert api.rejected == [5]


def test_replayed_reject_on_approved_is_noop(db):
    _admin(db, tg_id=444)
    api = FakeApiClient(dict(_READY, status="approved"))
    res = handlers.handle_reject(db, api, telegram_user_id=444, candidate_id=5)
    assert res.did_act is False
    assert api.rejected == []


def test_assign_lists_active_assignees_as_buttons(db):
    _admin(db, tg_id=611)
    api = FakeApiClient(dict(_READY, assignee_count=0))
    res = handlers.handle_assign(db, api, telegram_user_id=611, candidate_id=5)
    assert res.card is not None
    texts = [b.text for row in res.card.reply_markup.inline_keyboard for b in row]
    assert "Alice" in texts and "Bob" in texts


def test_assign_denied_for_unlinked(db):
    api = FakeApiClient(dict(_READY, assignee_count=0))
    res = handlers.handle_assign(db, api, telegram_user_id=70707, candidate_id=5)
    assert res.card is None
    assert "admin" in res.text.lower()


def test_pick_assignee_patches_candidate(db):
    _admin(db, tg_id=612)
    api = FakeApiClient(dict(_READY, assignee_count=0))
    res = handlers.handle_pick_assignee(db, api, telegram_user_id=612, candidate_id=5, assignee_id=11)
    assert res.did_act is True
    assert api.patched == [(5, {"assignee_ids": [11]})]


def test_pick_assignee_denied_for_non_admin(db):
    worker = m.User(email="w2@aiwip.local", role=m.UserRole.assignee)
    db.add(worker)
    db.flush()
    db.add(m.Assignee(display_name="W2", telegram_user_id=613, user_id=worker.id, is_active=True))
    db.flush()
    api = FakeApiClient(dict(_READY, assignee_count=0))
    res = handlers.handle_pick_assignee(db, api, telegram_user_id=613, candidate_id=5, assignee_id=11)
    assert res.did_act is False
    assert api.patched == []


def test_edit_is_authorized_but_directs_to_console(db):
    _admin(db, tg_id=614)
    api = FakeApiClient(_READY)
    res = handlers.handle_edit(db, api, telegram_user_id=614, candidate_id=5)
    assert res.did_act is False
    assert "console" in res.text.lower() or "web" in res.text.lower()
