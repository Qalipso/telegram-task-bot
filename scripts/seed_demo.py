"""Seed DEMO data for the web UI (dev only): assignees, labels, and candidates.

The live database holds the 42 synced Telegram messages but no extracted candidates
(extraction needs OPENAI_API_KEY, absent in this environment). This script inserts a
small, clearly-marked set of demo candidates so the review queue and board render real
content. Candidates are linked to real message rows by FK; their titles/summaries are
illustrative. Approval is left to be performed through the UI to demo the live flow.

Idempotent: re-running does nothing once the demo candidates exist (marker model_name).
Run it inside the api container:
    docker cp scripts/seed_demo.py aiwip-api-1:/tmp/seed_demo.py
    docker exec aiwip-api-1 python /tmp/seed_demo.py
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from aiwip_core.db import get_sessionmaker
from aiwip_core.models import (
    Assignee,
    Candidate,
    CandidateAssignee,
    CandidateMessage,
    CandidateMessageRole,
    CandidateStatus,
    CandidateType,
    Label,
    Message,
    Priority,
)

MARKER = "demo-seed"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _days(n: int) -> dt.datetime:
    return _now() + dt.timedelta(days=n)


def main() -> None:
    with get_sessionmaker()() as db:
        if db.execute(select(Candidate).where(Candidate.model_name == MARKER).limit(1)).scalar_one_or_none():
            print("demo data already present — nothing to do")
            return

        # real message ids to anchor candidates (FK targets)
        msg_ids = [m for (m,) in db.execute(select(Message.id).order_by(Message.id).limit(12)).all()]
        if not msg_ids:
            raise SystemExit("no messages in DB — sync first")

        def msg(i: int) -> int:
            return msg_ids[i % len(msg_ids)]

        # ---- assignees -------------------------------------------------------
        ivan = Assignee(display_name="Ivan", telegram_username="Иван", aliases=["Иван", "Vanya"], is_active=True)
        edot = Assignee(display_name="Eduard", telegram_username="edot3mple", aliases=["edot3mple", "Edot"], user_id=1, is_active=True)
        former = Assignee(display_name="Former Member", telegram_username="ghost", aliases=[], is_active=False)
        db.add_all([ivan, edot, former])
        db.flush()

        # ---- labels ----------------------------------------------------------
        labels = [
            Label(name="bug", color="#ef4444"),
            Label(name="feature", color="#3b82f6"),
            Label(name="content", color="#22c55e"),
            Label(name="urgent", color="#f59e0b"),
        ]
        for lb in labels:
            if not db.execute(select(Label).where(Label.name == lb.name)).scalar_one_or_none():
                db.add(lb)
        db.flush()

        # ---- candidates ------------------------------------------------------
        # (type, title, summary, priority, status, conf, missing, due_offset_days, assignee)
        specs = [
            (CandidateType.task, "Add a comments section under the post",
             "Implement a threaded comments block so readers can reply directly under each published post.",
             Priority.high, CandidateStatus.needs_review, 0.86, [], 2, ivan),
            (CandidateType.task, "Fix the cover image before launch",
             "The cover art needs a final correction pass and re-export before the launch goes out.",
             Priority.critical, CandidateStatus.new, 0.93, [], 1, edot),
            (CandidateType.request, "Review the new cover design",
             "Someone asked for a review of the updated cover — owner and deadline not stated.",
             Priority.medium, CandidateStatus.new, 0.71, ["due_date", "assignee"], None, None),
            (CandidateType.reminder, "Keep the publishing streak going",
             "Reminder to stay disciplined and not break the daily publishing streak.",
             Priority.low, CandidateStatus.new, 0.62, ["assignee"], 0, None),
            (CandidateType.idea, "Gamified discipline tracker",
             "Idea: a small gamified tracker for discipline/streaks to keep motivation high.",
             None, CandidateStatus.needs_review, 0.55, ["priority"], None, None),
            (CandidateType.knowledge, "Document the publishing workflow",
             "Capture how covers and posts get produced and shipped so the process is repeatable.",
             None, CandidateStatus.new, 0.80, [], None, edot),
        ]

        for i, (ctype, title, summary, prio, st, conf, missing, due_off, assignee) in enumerate(specs):
            c = Candidate(
                candidate_type=ctype,
                title=title,
                summary=summary,
                priority=prio,
                due_date=_days(due_off) if due_off is not None else None,
                status=st,
                task_confidence=conf,
                context_confidence=round(min(0.99, conf + 0.05), 2),
                assignee_confidence=(0.9 if assignee else 0.3),
                missing_fields=missing or None,
                reasoning_summary=f"Classified as {ctype.value} from the surrounding conversation; "
                                  f"confidence {conf:.0%}.",
                context_summary="Demo context window built from the synced Telegram thread.",
                model_name=MARKER,
                prompt_version="demo-v1",
            )
            db.add(c)
            db.flush()
            db.add(CandidateMessage(candidate_id=c.id, message_id=msg(i * 2), role=CandidateMessageRole.primary))
            db.add(CandidateMessage(candidate_id=c.id, message_id=msg(i * 2 + 1), role=CandidateMessageRole.context))
            if assignee is not None:
                db.add(CandidateAssignee(candidate_id=c.id, assignee_id=assignee.id, is_primary=True))

        db.commit()
        print(f"seeded: 3 assignees, {len(labels)} labels, {len(specs)} candidates (linked to real messages)")


if __name__ == "__main__":
    main()
