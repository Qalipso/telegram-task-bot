"""Phase glue — pure callback dispatch routing (host-testable, no aiogram). Real DB authz; fake API."""
from aiwip_bot import cards, dispatch
from aiwip_core import models as m

_CAND = {
    "id": 0, "candidate_type": "task", "title": "T", "summary": "S", "priority": "high",
    "due_date": None, "status": "new", "task_confidence": 0.95, "missing_fields": [],
    "assignee_count": 1, "assignee_ambiguous": False, "unresolved_mentions": None,
}


class FakeApi:
    def __init__(self, candidate: dict):
        self._candidate = candidate
        self.approved: list[int] = []
        self.rejected: list[int] = []
        self.patched: list[tuple[int, dict]] = []
        self.get_calls = 0

    def get_candidate(self, candidate_id: int) -> dict:
        self.get_calls += 1
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


def _admin(db, tg_id):
    u = m.User(email=f"a{tg_id}@x.io", role=m.UserRole.admin)
    db.add(u)
    db.flush()
    db.add(m.Assignee(display_name="A", telegram_user_id=tg_id, user_id=u.id, is_active=True))
    db.flush()
    return u


def test_dispatch_approve_for_admin(db):
    _admin(db, 111)
    api = FakeApi(_CAND)
    res = dispatch.dispatch_callback(db, api, cards.encode_callback("approve", 5), telegram_user_id=111)
    assert res.did_act is True and api.approved == [5]


def test_dispatch_reject_for_admin(db):
    _admin(db, 112)
    api = FakeApi(_CAND)
    res = dispatch.dispatch_callback(db, api, cards.encode_callback("reject", 5), telegram_user_id=112)
    assert res.did_act is True and api.rejected == [5]


def test_dispatch_assign_returns_picker_card(db):
    _admin(db, 113)
    api = FakeApi(dict(_CAND, assignee_count=0))
    res = dispatch.dispatch_callback(db, api, cards.encode_callback("assign", 5), telegram_user_id=113)
    assert res.did_act is False and res.card is not None
    texts = [b.text for row in res.card.reply_markup.inline_keyboard for b in row]
    assert "Alice" in texts and "Bob" in texts


def test_dispatch_pick_patches_candidate(db):
    _admin(db, 114)
    api = FakeApi(dict(_CAND, assignee_count=0))
    data = f"pick{cards.CB_SEP}5{cards.CB_SEP}11"
    res = dispatch.dispatch_callback(db, api, data, telegram_user_id=114)
    assert res.did_act is True and api.patched == [(5, {"assignee_ids": [11]})]


def test_dispatch_open_renders_card_for_admin(db):
    _admin(db, 115)
    api = FakeApi(_CAND)
    res = dispatch.dispatch_callback(db, api, cards.encode_callback("open", 5), telegram_user_id=115)
    assert res.card is not None and res.did_act is False
    assert api.get_calls == 1


def test_dispatch_open_denied_for_unlinked_does_no_api_io(db):
    api = FakeApi(_CAND)
    res = dispatch.dispatch_callback(db, api, cards.encode_callback("open", 5), telegram_user_id=99999)
    assert res.card is None and res.did_act is False
    assert "admin" in res.text.lower()
    assert api.get_calls == 0  # authz denied BEFORE any API I/O


def test_dispatch_malformed_is_denied_not_raised(db):
    api = FakeApi(_CAND)
    res = dispatch.dispatch_callback(db, api, "garbage-no-separator", telegram_user_id=111)
    assert res.did_act is False and res.card is None
    assert res.text  # a calm denial, not a crash


def test_dispatch_approve_denied_for_unlinked(db):
    api = FakeApi(_CAND)
    res = dispatch.dispatch_callback(db, api, cards.encode_callback("approve", 5), telegram_user_id=88888)
    assert res.did_act is False and api.approved == []


def test_dispatch_handles_stale_candidate_gracefully(db):
    """Approve on a card whose candidate was removed → calm denied result, never a crash."""
    from aiwip_bot import dispatch, cards
    from aiwip_bot.api_client import ConversationalApiError
    from aiwip_core import models as m

    u = m.User(email="adm@x.io", role=m.UserRole.admin)
    db.add(u); db.flush()
    db.add(m.Assignee(display_name="A", telegram_user_id=4242, user_id=u.id, is_active=True)); db.flush()

    class _StaleApi:
        def get_candidate(self, cid):
            raise ConversationalApiError("That item no longer exists — it may have been removed.", status_code=404)

    res = dispatch.dispatch_callback(db, _StaleApi(), cards.encode_callback("approve", 999), 4242)
    assert res.did_act is False
    assert "no longer exists" in res.text.lower()
