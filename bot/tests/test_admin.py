"""Admin panel — pure module tests.

Tests for admin.py formatting + webhook push, state.py webhook/pause helpers,
and the handle_approve webhook hook in handlers.py.
"""
from __future__ import annotations

import pytest

from aiwip_bot import admin, state
from aiwip_bot.handlers import handle_approve


# --------------------------------------------------------------------------- admin.py formatting


def test_dashboard_text_shows_all_counters():
    stats = {"chats": 1, "tasks_total": 5, "tasks_active": 5, "tasks_done": 0,
             "pending_review": 2, "rejected": 11}
    text = admin.dashboard_text(stats)
    assert "Подключено чатов: 1" in text
    assert "Всего задач создано: 5" in text
    assert "Активных задач: 5" in text
    assert "Закрыто задач: 0" in text
    assert "На ревью: 2" in text
    assert "Отклонено кандидатов: 11" in text


def test_dashboard_buttons_has_all_sections():
    labels = [b.callback_data for row in admin.dashboard_buttons() for b in row]
    assert "admin:tasks" in labels
    assert "admin:review" in labels
    assert "admin:chats" in labels
    assert "admin:history" in labels
    assert "admin:integrations" in labels
    assert "admin:menu" in labels  # refresh


def test_integrations_text_no_webhook_mentions_local_board():
    text = admin.integrations_text(None)
    assert "локальная борда" in text.lower()
    assert "/setwebhook" in text


def test_integrations_text_with_webhook():
    text = admin.integrations_text("https://hooks.zapier.com/abc")
    assert "hooks.zapier.com" in text
    assert "подключ" in text.lower()


def test_integrations_buttons_offer_set_when_missing():
    labels = [b.callback_data for row in admin.integrations_buttons(None) for b in row]
    assert "admin:integrations:help" in labels


def test_integrations_buttons_offer_clear_when_set():
    labels = [b.callback_data for row in admin.integrations_buttons("https://x.io/h") for b in row]
    assert "admin:integrations:clear" in labels


def test_review_text_empty():
    assert "пуст" in admin.review_text([]).lower()


def test_review_text_shows_pending_only():
    cands = [
        {"id": 1, "title": "Ship the report", "status": "new"},
        {"id": 2, "title": "Fix tests", "status": "needs_review"},
        {"id": 3, "title": "Already approved", "status": "approved"},
    ]
    text = admin.review_text(cands)
    assert "Ship the report" in text
    assert "Fix tests" in text
    assert "Already approved" not in text  # approved is not pending


def test_tasks_text_groups_by_priority_with_assignee_and_chat():
    work_items = [
        {"id": 8, "title": "сделай тесты", "status": "inbox", "priority": "high",
         "assignees": ["Эдуард"], "due_date": "2026-06-28T00:00:00+00:00",
         "source_chat_title": "Task Tracker"},
        {"id": 9, "title": "low one", "status": "inbox", "priority": "low", "assignees": []},
    ]
    text = admin.tasks_text(work_items)
    assert "WI-8" in text
    assert "Эдуард" in text
    assert "2026-06-28" in text
    assert "Task Tracker" in text
    assert "Высокий" in text and "Низкий" in text


def test_tasks_text_excludes_closed_from_active():
    work_items = [
        {"id": 1, "title": "active", "status": "inbox", "priority": "medium", "assignees": []},
        {"id": 2, "title": "finished", "status": "done", "priority": "medium", "assignees": []},
    ]
    active = admin.tasks_text(work_items, closed=False)
    assert "WI-1" in active and "WI-2" not in active
    closed = admin.tasks_text(work_items, closed=True)
    assert "WI-2" in closed and "WI-1" not in closed


def test_chats_text_empty():
    text = admin.chats_text([])
    assert "нет" in text.lower()


def test_chats_text_shows_titles():
    text = admin.chats_text([(-100123, "Work Chat"), (-100456, "Dev Team")])
    assert "Work Chat" in text
    assert "Dev Team" in text


def test_chats_buttons_open_detail():
    rows = admin.chats_buttons([(-100123, "Work Chat")])
    labels = [b.callback_data for row in rows for b in row]
    assert "admin:chat:-100123" in labels


def test_chat_detail_text_shows_counts_and_sync():
    text = admin.chat_detail_text(
        "Work Chat", {"total": 3, "active": 2, "closed": 1},
        "2026-06-27T13:56:00+00:00", paused=False,
    )
    assert "Work Chat" in text
    assert "Задач всего: 3" in text
    assert "Активных: 2" in text
    assert "Закрыто: 1" in text
    assert "2026-06-27 13:56" in text


def test_history_text_empty():
    text = admin.history_text([], {})
    assert "ничего" in text.lower() or "обработ" in text.lower()


def test_history_text_maps_approved_to_work_item_id():
    cands = [
        {"id": 58, "title": "add button for autotests", "status": "approved"},
        {"id": 57, "title": "B", "status": "rejected"},
        {"id": 59, "title": "C", "status": "needs_review"},
    ]
    wi_map = {58: 10}  # candidate 58 -> WI-10
    text = admin.history_text(cands, wi_map)
    assert "WI-10" in text       # approved shows the task id
    assert "#58" not in text     # not the raw candidate id
    assert "#57" in text         # rejected keeps candidate id
    assert "Создано задач: 1" in text
    assert "Отклонено: 1" in text


# --------------------------------------------------------------------------- webhook push


def test_push_webhook_success(monkeypatch):
    import httpx as _httpx

    class _FakeResp:
        status_code = 200

    monkeypatch.setattr(_httpx, "post", lambda *a, **kw: _FakeResp())
    result = admin.push_webhook({"id": 1, "title": "Task"}, "https://example.com/hook")
    assert result is True


def test_push_webhook_http_error_returns_false(monkeypatch):
    import httpx as _httpx

    class _FakeResp:
        status_code = 500

    monkeypatch.setattr(_httpx, "post", lambda *a, **kw: _FakeResp())
    result = admin.push_webhook({"id": 1}, "https://example.com/hook")
    assert result is False


def test_push_webhook_transport_error_returns_false(monkeypatch):
    import httpx as _httpx

    def _raise(*a, **kw):
        raise _httpx.ConnectError("down")

    monkeypatch.setattr(_httpx, "post", _raise)
    result = admin.push_webhook({"id": 1}, "https://example.com/hook")
    assert result is False


# --------------------------------------------------------------------------- state: webhook


def test_webhook_state_roundtrip():
    state.clear_admin_webhook()
    assert state.get_admin_webhook() is None
    state.set_admin_webhook("https://hooks.zapier.com/xyz")
    assert state.get_admin_webhook() == "https://hooks.zapier.com/xyz"
    state.clear_admin_webhook()
    assert state.get_admin_webhook() is None


# --------------------------------------------------------------------------- state: pause/resume


def test_pause_resume_roundtrip():
    cid = -100_999_001
    state.resume_chat(cid)  # ensure clean start
    assert not state.is_chat_paused(cid)
    state.pause_chat(cid)
    assert state.is_chat_paused(cid)
    state.resume_chat(cid)
    assert not state.is_chat_paused(cid)


# --------------------------------------------------------------------------- state: list_configured_chats


def test_list_configured_chats_includes_set_chat():
    cid = -100_999_002
    state.clear_chat_config(cid)
    assert cid not in state.list_configured_chats()
    state.set_chat_config(cid, destination="internal")
    assert cid in state.list_configured_chats()
    state.clear_chat_config(cid)


# --------------------------------------------------------------------------- handlers: handle_approve webhook hook


class _FakeApi:
    """Minimal fake to exercise the webhook-push side-effect."""
    def __init__(self, work_item):
        self._wi = work_item
        self.approved = []

    def get_candidate(self, cid):
        return {"candidate": {"id": cid, "status": "new", "missing_fields": [], "unresolved_mentions": []}}

    def approve_candidate(self, cid):
        self.approved.append(cid)
        return self._wi


class _FakeDb:
    def query(self, *a):
        return self

    def filter_by(self, **kw):
        return self

    def first(self):
        return None  # not admin → authorize_tapper returns denied
                     # we bypass via _push_fn param, not authz test


def test_handle_approve_calls_push_fn_on_success(db):
    """handle_approve calls the injected _push_fn with the returned work_item."""
    from aiwip_core import models as m

    wi = {"id": 99, "title": "Done"}
    api = _FakeApi(wi)
    called = []

    # Set up a linked admin user so authz passes
    user = m.User(email="admin@test.com", role=m.UserRole.admin)
    db.add(user)
    db.flush()
    assignee = m.Assignee(display_name="Admin", telegram_user_id=700001, is_active=True)
    db.add(assignee)
    db.flush()
    user.assignee = assignee
    db.flush()

    result = handle_approve(db, api, 700001, 42, _push_fn=lambda wi: called.append(wi))
    assert result.did_act is True
    assert called == [wi]


def test_handle_approve_no_push_when_denied(db):
    """_push_fn must NOT be called when the tapper is not an admin."""
    wi = {"id": 99}
    api = _FakeApi(wi)
    called = []

    result = handle_approve(db, api, 999999, 42, _push_fn=lambda wi: called.append(wi))
    assert result.did_act is False
    assert called == []
