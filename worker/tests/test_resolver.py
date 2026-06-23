"""Stage 6 — assignee resolver foundation."""
from aiwip_core import models as m
from aiwip_worker import resolver


def _assignee(db, **kw):
    a = m.Assignee(**kw)
    db.add(a)
    db.flush()
    return a


def test_resolve_by_username_display_and_alias(db):
    bob = _assignee(db, display_name="Bob Smith", telegram_username="bobsmith", aliases=["Bobby"])
    assert resolver.resolve_assignees(db, "@bobsmith") == [bob]
    assert resolver.resolve_assignees(db, "Bob Smith") == [bob]
    assert resolver.resolve_assignees(db, "bobby") == [bob]  # case-insensitive alias


def test_resolver_only_active(db):
    _assignee(db, display_name="Ghost", telegram_username="ghost", is_active=False)
    assert resolver.resolve_assignees(db, "ghost") == []


def test_resolver_ambiguous_returns_multiple(db):
    a1 = _assignee(db, display_name="Alex", telegram_username="alex1", aliases=["lead"])
    a2 = _assignee(db, display_name="Alexandra", telegram_username="alex2", aliases=["lead"])
    matches = resolver.resolve_assignees(db, "lead")
    assert set(matches) == {a1, a2}


def test_resolver_unknown_and_empty(db):
    _assignee(db, display_name="Bob", telegram_username="bob")
    assert resolver.resolve_assignees(db, "nobody") == []
    assert resolver.resolve_assignees(db, "") == []
    assert resolver.resolve_assignees(db, "   @  ") == []
