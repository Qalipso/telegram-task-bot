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


def test_handle_approve_push_failure_does_not_fail_approval(db):
    """A raising push side-effect must NOT surface as a failed approval (candidate is already
    approved server-side). Regression: httpx.InvalidURL from a malformed stored webhook URL is
    NOT an httpx.HTTPError, so it escaped push_webhook and propagated out of handle_approve."""
    from aiwip_core import models as m

    wi = {"id": 99, "title": "Done"}
    api = _FakeApi(wi)

    user = m.User(email="admin2@test.com", role=m.UserRole.admin)
    db.add(user)
    db.flush()
    assignee = m.Assignee(display_name="Admin2", telegram_user_id=700002, is_active=True)
    db.add(assignee)
    db.flush()
    user.assignee = assignee
    db.flush()

    def _boom(_wi):
        raise RuntimeError("webhook layer blew up")

    result = handle_approve(db, api, 700002, 42, _push_fn=_boom)
    assert result.did_act is True          # the approval itself stands
    assert api.approved == [42]            # candidate was approved server-side


def test_push_webhook_invalid_url_returns_false(monkeypatch):
    """httpx.InvalidURL (NOT a subclass of httpx.HTTPError) must be caught, not raised."""
    import httpx as _httpx

    def _raise(*a, **kw):
        raise _httpx.InvalidURL("no host in URL")

    monkeypatch.setattr(_httpx, "post", _raise)
    assert admin.push_webhook({"id": 1}, "http://") is False


# --------------------------------------------------------------------------- pure aggregators

def test_dashboard_counters_math():
    work_items = [
        {"id": 1, "status": "inbox"},
        {"id": 2, "status": "in_progress"},
        {"id": 3, "status": "done"},
        {"id": 4, "status": "archived"},
        {"id": 5, "status": "cancelled"},
    ]
    candidates = [
        {"id": 1, "status": "new"},
        {"id": 2, "status": "needs_review"},
        {"id": 3, "status": "edited"},
        {"id": 4, "status": "rejected"},
        {"id": 5, "status": "rejected"},
        {"id": 6, "status": "approved"},
    ]
    c = admin.dashboard_counters(work_items, candidates)
    assert c["tasks_total"] == 5
    assert c["tasks_done"] == 3          # done + archived + cancelled
    assert c["tasks_active"] == 2        # total - closed
    assert c["pending_review"] == 3      # new + needs_review + edited
    assert c["rejected"] == 2


def test_chat_task_stats_filters_by_chat():
    work_items = [
        {"id": 1, "status": "inbox", "source_chat_id": -100},
        {"id": 2, "status": "done", "source_chat_id": -100},
        {"id": 3, "status": "inbox", "source_chat_id": -200},
    ]
    s = admin.chat_task_stats(work_items, -100)
    assert s == {"total": 2, "active": 1, "closed": 1}
    assert admin.chat_task_stats(work_items, -999) == {"total": 0, "active": 0, "closed": 0}


def test_build_wi_map_skips_null_source_candidate():
    work_items = [
        {"id": 10, "source_candidate_id": 58},
        {"id": 11, "source_candidate_id": None},   # manual WI, no candidate — must be skipped
        {"id": 12},                                 # missing key — must be skipped
    ]
    assert admin.build_wi_map(work_items) == {58: 10}


# --------------------------------------------------------------------------- webhook SSRF guard
# Policy (chosen 2026-06-27): https-only; block loopback + link-local / cloud-metadata.

def _ok_resolver(_host, _port, **kw):
    # pretend the host resolves to a public IP
    return [(2, 1, 6, "", ("93.184.216.34", _port))]


def test_validate_webhook_rejects_non_https():
    assert admin.validate_webhook_url("http://hooks.zapier.com/x", _resolve=_ok_resolver) is not None
    assert admin.validate_webhook_url("ftp://x/y", _resolve=_ok_resolver) is not None
    assert admin.validate_webhook_url("httpfoo://x", _resolve=_ok_resolver) is not None


def test_validate_webhook_rejects_localhost_and_no_host():
    assert admin.validate_webhook_url("https://localhost/hook", _resolve=_ok_resolver) is not None
    assert admin.validate_webhook_url("https://", _resolve=_ok_resolver) is not None


def test_validate_webhook_blocks_loopback_and_metadata_literals():
    # numeric hosts don't need DNS — the real resolver returns them as-is
    assert admin.validate_webhook_url("https://127.0.0.1/hook") is not None       # loopback
    assert admin.validate_webhook_url("https://169.254.169.254/latest/") is not None  # cloud metadata (link-local)
    assert admin.validate_webhook_url("https://[::1]/hook") is not None           # ipv6 loopback


def test_validate_webhook_blocks_public_host_resolving_to_metadata():
    def _evil_resolver(_host, _port, **kw):
        return [(2, 1, 6, "", ("169.254.169.254", _port))]
    assert admin.validate_webhook_url("https://innocent.example.com/h", _resolve=_evil_resolver) is not None


def test_validate_webhook_allows_public_https():
    assert admin.validate_webhook_url("https://hooks.zapier.com/abc", _resolve=_ok_resolver) is None
    # a literal public IP over https is fine too
    assert admin.validate_webhook_url("https://93.184.216.34/h") is None
