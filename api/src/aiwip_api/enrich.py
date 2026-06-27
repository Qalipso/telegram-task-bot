"""Batch enrichment: resolve each item's source chat + assignee names in O(1) queries.

The list endpoints return many work items / candidates. Resolving the source chat
(item → candidate → message → chat) and assignee display names per-item would be N+1.
These helpers do a single grouped query per relationship and stitch the results in Python.
"""
from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from aiwip_api.schemas import CandidateOut, WorkItemOut
from aiwip_core.models import (
    Assignee,
    Candidate,
    CandidateAssignee,
    CandidateMessage,
    Chat,
    Message,
    WorkItem,
    WorkItemAssignee,
)


def _chat_by_candidate(db: Session, candidate_ids: Sequence[int]) -> dict[int, tuple[int, str | None]]:
    """candidate_id -> (external_chat_id, chat_title). First-linked message's chat wins."""
    if not candidate_ids:
        return {}
    rows = db.execute(
        select(CandidateMessage.candidate_id, Chat.external_chat_id, Chat.title)
        .join(Message, Message.id == CandidateMessage.message_id)
        .join(Chat, Chat.id == Message.chat_id)
        .where(CandidateMessage.candidate_id.in_(candidate_ids))
        .order_by(CandidateMessage.candidate_id, CandidateMessage.message_id)
    ).all()
    out: dict[int, tuple[int, str | None]] = {}
    for cand_id, ext_id, title in rows:
        out.setdefault(cand_id, (ext_id, title))  # first message per candidate wins
    return out


def _names_by_work_item(db: Session, work_item_ids: Sequence[int]) -> dict[int, list[str]]:
    """work_item_id -> [display_name, ...] (primary assignee first)."""
    if not work_item_ids:
        return {}
    rows = db.execute(
        select(
            WorkItemAssignee.work_item_id,
            Assignee.display_name,
            Assignee.telegram_username,
        )
        .join(Assignee, Assignee.id == WorkItemAssignee.assignee_id)
        .where(WorkItemAssignee.work_item_id.in_(work_item_ids))
        .order_by(WorkItemAssignee.work_item_id, WorkItemAssignee.is_primary.desc())
    ).all()
    out: dict[int, list[str]] = {}
    for wid, display_name, username in rows:
        out.setdefault(wid, []).append(display_name or username or "?")
    return out


def _names_by_candidate(db: Session, candidate_ids: Sequence[int]) -> dict[int, list[str]]:
    """candidate_id -> [display_name, ...] (primary assignee first)."""
    if not candidate_ids:
        return {}
    rows = db.execute(
        select(
            CandidateAssignee.candidate_id,
            Assignee.display_name,
            Assignee.telegram_username,
        )
        .join(Assignee, Assignee.id == CandidateAssignee.assignee_id)
        .where(CandidateAssignee.candidate_id.in_(candidate_ids))
        .order_by(CandidateAssignee.candidate_id, CandidateAssignee.is_primary.desc())
    ).all()
    out: dict[int, list[str]] = {}
    for cand_id, display_name, username in rows:
        out.setdefault(cand_id, []).append(display_name or username or "?")
    return out


def work_items_out(db: Session, items: Sequence[WorkItem]) -> list[WorkItemOut]:
    """Serialize work items with assignee names + source chat attached."""
    names = _names_by_work_item(db, [w.id for w in items])
    chats = _chat_by_candidate(db, [w.source_candidate_id for w in items])
    result: list[WorkItemOut] = []
    for w in items:
        ext_id, title = chats.get(w.source_candidate_id, (None, None))
        result.append(
            WorkItemOut.model_validate(w).model_copy(
                update={
                    "assignees": names.get(w.id, []),
                    "source_chat_id": ext_id,
                    "source_chat_title": title,
                }
            )
        )
    return result


def candidates_out(db: Session, items: Sequence[Candidate]) -> list[CandidateOut]:
    """Serialize candidates with source chat + resolved assignee names attached."""
    ids = [c.id for c in items]
    chats = _chat_by_candidate(db, ids)
    names = _names_by_candidate(db, ids)
    result: list[CandidateOut] = []
    for c in items:
        ext_id, title = chats.get(c.id, (None, None))
        result.append(
            CandidateOut.model_validate(c).model_copy(
                update={
                    "source_chat_id": ext_id,
                    "source_chat_title": title,
                    "assignees": names.get(c.id, []),
                }
            )
        )
    return result
