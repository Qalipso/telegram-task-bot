"""Context Builder — assemble an analysis window from stored messages.

MVP strategy (per implementation-plan §5): a FIXED window of the last ~20 content messages plus
reply-referenced messages, segmented by a time-gap heuristic so a new topic doesn't pollute the
previous one. No ML segmentation. The window is passed to the AI pipeline (Stage 8); the LLM
produces the authoritative context_summary/confidence — here we attach lightweight heuristics.

This is a HIGH-RISK component: if window quality is weak, candidate quality suffers. Keep it simple
and eval-driven.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from aiwip_core.logging import get_logger
from aiwip_core.models import Message, MessageProcessingStatus

logger = get_logger("aiwip.worker.context")

DEFAULT_WINDOW = 20
DEFAULT_TOPIC_GAP_MINUTES = 60


@dataclass
class ContextMessage:
    external_message_id: int
    sender: str | None
    sent_at_utc: str | None
    text: str | None
    reply_to: int | None


@dataclass
class ContextWindow:
    chat_id: int
    messages: list[ContextMessage]
    summary: str
    confidence: float

    def to_dict(self) -> dict:
        return asdict(self)


def _text(message: Message) -> str | None:
    return message.normalized_content or message.text_content


def _reply_to(message: Message) -> int | None:
    return (message.raw_payload or {}).get("reply_to")


def _recent_content_messages(db: Session, chat_id: int, limit: int, new_only: bool = False) -> list[Message]:
    query = select(Message).where(Message.chat_id == chat_id, Message.text_content.isnot(None))
    if new_only:
        # only messages not yet run through extraction — prevents re-extracting already-analyzed
        # messages into duplicate candidates on a later sync
        query = query.where(Message.processing_status == MessageProcessingStatus.normalized)
    rows = db.execute(
        query.order_by(Message.external_message_id.desc()).limit(limit)
    ).scalars().all()
    return list(reversed(rows))  # ascending


def _recent_topic_segment(messages: list[Message], gap_minutes: int) -> list[Message]:
    """The most-recent contiguous run of messages whose neighbour gap stays within the threshold."""
    if not messages:
        return []
    gap = dt.timedelta(minutes=gap_minutes)
    segment = [messages[-1]]
    for message in reversed(messages[:-1]):
        oldest_in_segment = segment[0]
        if (
            oldest_in_segment.sent_at
            and message.sent_at
            and (oldest_in_segment.sent_at - message.sent_at) <= gap
        ):
            segment.insert(0, message)
        else:
            break  # a large gap = topic boundary; stop here
    return segment


def _with_reply_references(db: Session, chat_id: int, segment: list[Message]) -> list[Message]:
    seg_ids = {m.external_message_id for m in segment}
    referenced = {rt for m in segment if (rt := _reply_to(m)) and rt not in seg_ids}
    if not referenced:
        return segment
    extra = db.execute(
        select(Message).where(Message.chat_id == chat_id, Message.external_message_id.in_(referenced))
    ).scalars().all()
    merged = {m.external_message_id: m for m in segment}
    for m in extra:
        merged[m.external_message_id] = m
    return sorted(merged.values(), key=lambda m: m.external_message_id)


def _summarize(messages: list[ContextMessage]) -> str:
    if not messages:
        return "empty context"
    senders = sorted({m.sender for m in messages if m.sender})
    who = ", ".join(senders[:5]) if senders else "unknown"
    return f"{len(messages)} message(s) from {len(senders) or '?'} participant(s): {who}"


def _confidence(recent: list[Message], segment: list[Message]) -> float:
    if not segment:
        return 0.0
    size_factor = min(len(segment) / 5, 1.0) * 0.6  # reward a non-trivial window (≥5 → 0.6)
    cohesion = (len(segment) / max(len(recent), 1)) * 0.4  # how much of the window is one topic
    return round(min(size_factor + cohesion, 1.0), 2)


def build_context(
    db: Session, chat_id: int, window: int = DEFAULT_WINDOW, topic_gap_minutes: int = DEFAULT_TOPIC_GAP_MINUTES,
    new_only: bool = False,
) -> ContextWindow:
    recent = _recent_content_messages(db, chat_id, window, new_only=new_only)
    segment = _recent_topic_segment(recent, topic_gap_minutes)
    segment = _with_reply_references(db, chat_id, segment)
    ctx_messages = [
        ContextMessage(
            external_message_id=m.external_message_id,
            sender=m.sender_username or m.sender_display_name,
            sent_at_utc=m.sent_at.astimezone(dt.timezone.utc).isoformat() if m.sent_at else None,
            text=_text(m),
            reply_to=_reply_to(m),
        )
        for m in segment
    ]
    ctx = ContextWindow(
        chat_id=chat_id,
        messages=ctx_messages,
        summary=_summarize(ctx_messages),
        confidence=_confidence(recent, segment),
    )
    logger.info(
        "context chat=%s window=%s msgs (of %s recent) conf=%.2f", chat_id, len(ctx_messages), len(recent), ctx.confidence
    )
    return ctx
