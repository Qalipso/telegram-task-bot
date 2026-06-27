"""Analytics overview: read-only aggregation for the web dashboard (admin-only).

The aggregation math lives in pure module-level functions (unit-tested in isolation); the router
just fetches rows, maps them to plain dicts, and calls these. No writes, ever.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from aiwip_api import auth
from aiwip_core.models import (
    Assignee,
    Candidate,
    SyncRun,
    User,
    WorkItem,
    WorkItemAssignee,
    WorkItemStatus,
)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

# A work item is "closed" (off the active board) once it reaches one of these.
CLOSED_STATUSES = {"done", "cancelled", "archived"}
_STATUS_ORDER = [s.value for s in WorkItemStatus]
_PRIORITY_ORDER = ["critical", "high", "medium", "low"]
_CONF_BUCKETS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0001)]


def _as_date(iso: str | None) -> date | None:
    if not iso:
        return None
    return datetime.fromisoformat(iso).date()


# --------------------------------------------------------------------------- pure aggregators

def compute_kpis(work_items: list[dict], candidates: list[dict], today: date) -> dict:
    closed = sum(1 for w in work_items if w.get("status") in CLOSED_STATUSES)
    total = len(work_items)
    overdue = sum(
        1 for w in work_items
        if w.get("status") not in CLOSED_STATUSES
        and (d := _as_date(w.get("due_date"))) is not None and d < today
    )
    approved = sum(1 for c in candidates if c.get("status") == "approved")
    rejected = sum(1 for c in candidates if c.get("status") == "rejected")
    decided = approved + rejected
    confs = [w["confidence"] for w in work_items if w.get("confidence") is not None]
    return {
        "tasks_total": total,
        "tasks_active": total - closed,
        "tasks_done": closed,
        "tasks_overdue": overdue,
        "approval_rate": round(approved / decided, 3) if decided else 0.0,
        "avg_extraction_confidence": round(sum(confs) / len(confs), 3) if confs else 0.0,
    }


def tasks_over_time(work_items: list[dict], candidates: list[dict], days: int, today: date) -> list[dict]:
    """One point per day for the last `days` days: candidates captured + tasks created (approved)."""
    from datetime import timedelta
    span = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    cand_by_day = Counter(_as_date(c.get("created_at")) for c in candidates)
    wi_by_day = Counter(_as_date(w.get("created_at")) for w in work_items)
    return [
        {"date": d.isoformat(), "candidates": cand_by_day.get(d, 0), "approved": wi_by_day.get(d, 0)}
        for d in span
    ]


def status_distribution(work_items: list[dict]) -> list[dict]:
    counts = Counter(w.get("status") for w in work_items)
    return [{"status": s, "count": counts[s]} for s in _STATUS_ORDER if counts.get(s)]


def priority_distribution(work_items: list[dict]) -> list[dict]:
    counts = Counter(w.get("priority") for w in work_items)
    return [{"priority": p, "count": counts[p]} for p in _PRIORITY_ORDER if counts.get(p)]


def funnel(sync_runs: list[dict], candidates: list[dict]) -> dict:
    return {
        "messages": sum(r.get("messages_saved") or 0 for r in sync_runs),
        "candidates": len(candidates),
        "approved": sum(1 for c in candidates if c.get("status") == "approved"),
        "rejected": sum(1 for c in candidates if c.get("status") == "rejected"),
    }


def confidence_histogram(candidates: list[dict], field: str = "task_confidence") -> list[dict]:
    out = []
    for lo, hi in _CONF_BUCKETS:
        n = sum(1 for c in candidates if (v := c.get(field)) is not None and lo <= v < hi)
        out.append({"bucket": f"{lo:.1f}–{min(hi, 1.0):.1f}", "count": n})
    return out


def assignee_workload(rows: list[tuple[str, str]]) -> list[dict]:
    """rows: (assignee_display_name, work_item_status). Returns active/total per assignee, busiest first."""
    agg: dict[str, dict] = {}
    for name, status in rows:
        a = agg.setdefault(name, {"name": name, "active": 0, "total": 0})
        a["total"] += 1
        if status not in CLOSED_STATUSES:
            a["active"] += 1
    return sorted(agg.values(), key=lambda a: (a["active"], a["total"]), reverse=True)


# --------------------------------------------------------------------------- endpoint

@router.get("/overview")
def overview(
    days: int = Query(14, ge=1, le=90),
    _admin: User = Depends(auth.require_admin),
    db: Session = Depends(auth.get_db),
):
    work_items = [
        {"status": w.status, "due_date": w.due_date.isoformat() if w.due_date else None,
         "confidence": w.confidence, "priority": w.priority,
         "created_at": w.created_at.isoformat() if w.created_at else None}
        for w in db.execute(select(WorkItem)).scalars().all()
    ]
    candidates = [
        {"status": c.status, "task_confidence": c.task_confidence,
         "created_at": c.created_at.isoformat() if c.created_at else None}
        for c in db.execute(select(Candidate)).scalars().all()
    ]
    sync_runs = [{"messages_saved": r.messages_saved} for r in db.execute(select(SyncRun)).scalars().all()]
    wl_rows = db.execute(
        select(Assignee.display_name, WorkItem.status)
        .join(WorkItemAssignee, WorkItemAssignee.assignee_id == Assignee.id)
        .join(WorkItem, WorkItem.id == WorkItemAssignee.work_item_id)
    ).all()

    today = datetime.now(timezone.utc).date()
    return {
        "kpis": compute_kpis(work_items, candidates, today),
        "tasks_over_time": tasks_over_time(work_items, candidates, days, today),
        "status_distribution": status_distribution(work_items),
        "priority_distribution": priority_distribution(work_items),
        "funnel": funnel(sync_runs, candidates),
        "confidence_histogram": confidence_histogram(candidates),
        "assignee_workload": assignee_workload([(n, s) for n, s in wl_rows]),
    }
