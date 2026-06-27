"""Analytics overview — pure aggregators + the admin-only /api/analytics/overview endpoint."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from aiwip_api import analytics, auth
from aiwip_core import models as m


# --------------------------------------------------------------------------- pure aggregators

def test_compute_kpis_math():
    today = date(2026, 6, 27)
    work_items = [
        {"status": "inbox", "due_date": None, "confidence": 0.9},
        {"status": "in_progress", "due_date": "2026-06-20T00:00:00+00:00", "confidence": 0.7},  # overdue
        {"status": "done", "due_date": "2026-06-01T00:00:00+00:00", "confidence": 0.8},          # closed, not overdue
        {"status": "archived", "due_date": None, "confidence": None},                            # closed
    ]
    candidates = [
        {"status": "approved"}, {"status": "approved"},
        {"status": "rejected"}, {"status": "new"},
    ]
    k = analytics.compute_kpis(work_items, candidates, today)
    assert k["tasks_total"] == 4
    assert k["tasks_done"] == 2          # done + archived
    assert k["tasks_active"] == 2
    assert k["tasks_overdue"] == 1       # only the in_progress past-due one
    assert k["approval_rate"] == 0.667   # 2 approved / (2 approved + 1 rejected)
    assert k["avg_extraction_confidence"] == 0.8  # mean of 0.9,0.7,0.8 (None skipped)


def test_compute_kpis_handles_empty():
    k = analytics.compute_kpis([], [], date(2026, 6, 27))
    assert k["tasks_total"] == 0
    assert k["approval_rate"] == 0.0
    assert k["avg_extraction_confidence"] == 0.0


def test_tasks_over_time_buckets_by_day():
    today = date(2026, 6, 27)
    work_items = [{"created_at": "2026-06-27T10:00:00+00:00"}, {"created_at": "2026-06-26T10:00:00+00:00"}]
    candidates = [
        {"created_at": "2026-06-27T09:00:00+00:00"},
        {"created_at": "2026-06-27T11:00:00+00:00"},
        {"created_at": "2026-06-25T11:00:00+00:00"},
    ]
    series = analytics.tasks_over_time(work_items, candidates, days=3, today=today)
    assert [p["date"] for p in series] == ["2026-06-25", "2026-06-26", "2026-06-27"]
    assert series[0] == {"date": "2026-06-25", "candidates": 1, "approved": 0}
    assert series[2] == {"date": "2026-06-27", "candidates": 2, "approved": 1}


def test_status_distribution_orders_and_counts():
    work_items = [{"status": "inbox"}, {"status": "inbox"}, {"status": "done"}]
    dist = analytics.status_distribution(work_items)
    assert {"status": "inbox", "count": 2} in dist
    assert {"status": "done", "count": 1} in dist
    # canonical WorkItemStatus order is preserved (inbox before done)
    assert [d["status"] for d in dist].index("inbox") < [d["status"] for d in dist].index("done")


def test_funnel_counts():
    sync_runs = [{"messages_saved": 10}, {"messages_saved": 5}, {"messages_saved": None}]
    candidates = [{"status": "approved"}, {"status": "rejected"}, {"status": "rejected"}, {"status": "new"}]
    f = analytics.funnel(sync_runs, candidates)
    assert f == {"messages": 15, "candidates": 4, "approved": 1, "rejected": 2}


def test_confidence_histogram_bins():
    candidates = [
        {"task_confidence": 0.05}, {"task_confidence": 0.55}, {"task_confidence": 0.95},
        {"task_confidence": 0.99}, {"task_confidence": None},
    ]
    hist = analytics.confidence_histogram(candidates)
    buckets = {h["bucket"]: h["count"] for h in hist}
    assert buckets["0.0–0.2"] == 1
    assert buckets["0.4–0.6"] == 1
    assert buckets["0.8–1.0"] == 2  # 0.95 and 0.99; None skipped
    assert sum(h["count"] for h in hist) == 4


def test_assignee_workload():
    rows = [
        ("Eduard", "inbox"), ("Eduard", "done"), ("Eduard", "in_progress"),
        ("Maria", "inbox"),
    ]
    wl = analytics.assignee_workload(rows)
    by_name = {w["name"]: w for w in wl}
    assert by_name["Eduard"] == {"name": "Eduard", "active": 2, "total": 3}
    assert by_name["Maria"] == {"name": "Maria", "active": 1, "total": 1}
    # sorted by active desc → Eduard first
    assert wl[0]["name"] == "Eduard"


# --------------------------------------------------------------------------- endpoint

def _login(client, db, role, email):
    db.add(m.User(email=email, role=role, password_hash=auth.hash_password("pw123456")))
    db.flush()
    client.post("/api/auth/login", json={"email": email, "password": "pw123456"})


def test_overview_unauthenticated(client):
    assert client.get("/api/analytics/overview").status_code == 401


def test_overview_admin_only(client, db):
    _login(client, db, m.UserRole.assignee, "ass@x.io")
    assert client.get("/api/analytics/overview").status_code == 403


def test_overview_shape_and_live_counts(client, db):
    _login(client, db, m.UserRole.admin, "admin@x.io")
    # seed one approved candidate + its promoted work item
    cand = m.Candidate(candidate_type=m.CandidateType.task, title="Ship", status=m.CandidateStatus.approved,
                       task_confidence=0.9)
    db.add(cand)
    db.flush()
    db.add(m.WorkItem(source_candidate_id=cand.id, type=m.WorkItemType.task, title="Ship",
                      status=m.WorkItemStatus.inbox, confidence=0.9))
    db.flush()

    body = client.get("/api/analytics/overview").json()
    for key in ("kpis", "tasks_over_time", "status_distribution", "priority_distribution",
                "funnel", "confidence_histogram", "assignee_workload"):
        assert key in body, f"missing {key}"
    assert body["kpis"]["tasks_total"] == 1
    assert body["funnel"]["approved"] == 1
