"""Reset the review demo to a clean, reproducible state for a screencast.

- wipes existing candidates + work items (and their link rows),
- ensures the demo assignees exist and are bound to a unique Telegram user id
  (using the real sender id from synced messages when available),
- re-extracts the most-recent context window for each chat with the LIVE prompt,
  so the review queue shows fresh candidates with High/Mid/Low priorities and
  related-only source messages.

Run inside the worker container (needs OPENAI_API_KEY + DB):
    docker cp scripts/reset_demo.py aiwip-worker-1:/tmp/reset_demo.py
    docker exec aiwip-worker-1 python /tmp/reset_demo.py
"""
from __future__ import annotations

from sqlalchemy import delete, select

from aiwip_core.db import get_sessionmaker
from aiwip_core.models import (
    Assignee,
    Candidate,
    CandidateAssignee,
    CandidateLabel,
    CandidateMessage,
    Chat,
    Message,
    MessageProcessingStatus,
    WorkItem,
    WorkItemAssignee,
    WorkItemLabel,
)
from aiwip_worker import context as ctxmod
from aiwip_worker import extract

# display_name -> (telegram usernames to look up a real id, fallback placeholder id)
ASSIGNEES = {
    "Ivan": (["Иван", "Vanya"], 100100100),
    "Eduard": (["edot3mple", "Edot"], 200200200),
    "Former Member": (["ghost"], 300300300),
}


def _real_tg_id(db, usernames):
    for u in usernames:
        row = db.execute(
            select(Message.sender_external_id)
            .where(Message.sender_username == u, Message.sender_external_id.isnot(None))
            .limit(1)
        ).scalar_one_or_none()
        if row:
            return int(row)
    return None


def main() -> None:
    with get_sessionmaker()() as db:
        # 1. wipe work items + candidates (children first to satisfy FKs)
        for model in (
            WorkItemAssignee, WorkItemLabel, WorkItem,
            CandidateMessage, CandidateAssignee, CandidateLabel, Candidate,
        ):
            db.execute(delete(model))
        db.commit()

        # 2. ensure assignees exist + bound to a unique Telegram id
        for name, (usernames, fallback) in ASSIGNEES.items():
            tg_id = _real_tg_id(db, usernames) or fallback
            a = db.execute(select(Assignee).where(Assignee.display_name == name)).scalar_one_or_none()
            if a is None:
                a = Assignee(display_name=name, telegram_username=usernames[0], aliases=usernames, is_active=(name != "Former Member"))
                db.add(a)
            a.telegram_user_id = tg_id
            print(f"assignee {name}: telegram_user_id={tg_id}")
        db.commit()

        # 3. re-arm ONLY the most-recent topic segment per chat (older messages stay 'analyzed' so
        #    they are not re-processed), then re-extract a clean single batch with the live prompt.
        total = 0
        for chat in db.execute(select(Chat)).scalars().all():
            recent = ctxmod._recent_content_messages(db, chat.id, ctxmod.DEFAULT_WINDOW)
            segment_ids = {msg.id for msg in ctxmod._recent_topic_segment(recent, ctxmod.DEFAULT_TOPIC_GAP_MINUTES)}
            for msg in db.execute(
                select(Message).where(Message.chat_id == chat.id, Message.processing_status != MessageProcessingStatus.skipped)
            ).scalars():
                msg.processing_status = (
                    MessageProcessingStatus.normalized if msg.id in segment_ids else MessageProcessingStatus.analyzed
                )
            db.commit()
            created = extract.extract_candidates(db, chat.id)
            total += len(created)
            print(f"chat {chat.id}: extracted {len(created)} candidate(s) from {len(segment_ids)} segment msg(s)")

        # 4. demo safety: drop any duplicate-title candidates (keep the earliest)
        seen: set[str] = set()
        dups: list[int] = []
        for c in db.execute(select(Candidate).order_by(Candidate.id)).scalars().all():
            key = (c.title or "").strip().lower()
            (dups.append(c.id) if key in seen else seen.add(key))
        if dups:
            for model in (CandidateMessage, CandidateAssignee, CandidateLabel):
                db.execute(delete(model).where(model.candidate_id.in_(dups)))
            db.execute(delete(Candidate).where(Candidate.id.in_(dups)))
            db.commit()
            print(f"removed {len(dups)} duplicate-title candidate(s)")

        # 5. mark the re-armed messages 'analyzed' so the next sync won't re-extract them
        for chat in db.execute(select(Chat)).scalars().all():
            db.query(Message).filter(
                Message.chat_id == chat.id, Message.processing_status == MessageProcessingStatus.normalized
            ).update({Message.processing_status: MessageProcessingStatus.analyzed})
        db.commit()
        print(f"done — {total - len(dups)} candidate(s) in the review queue")


if __name__ == "__main__":
    main()
