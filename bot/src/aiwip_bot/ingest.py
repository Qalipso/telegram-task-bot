"""Forward-only ingestion: inbound Bot API message → Redis buffer → debounced sync job.

The bot RPUSHes each post-join message to aiwip:botbuf:{chat} (drained later by the worker's
BotApiConnector). To avoid one LLM extraction per chat line, enqueue is debounced via a Redis
lock aiwip:botlock:{chat}: the first message in a quiet window enqueues a single telegram.sync
job; everything else in the window only buffers. The one job drains the whole buffer (design §4.2).

The configure-before-capture gate (design §7) delegates to Phase 5's canonical predicate
state.is_chat_configured (backed by aiwip:botcfg:{chat}); an unconfigured chat captures nothing.
"""
from __future__ import annotations

import datetime as dt

from aiwip_core import queue
from aiwip_core.redis_client import get_redis

BOTLOCK_PREFIX = "aiwip:botlock:"


def _botlock_key(external_chat_id: int) -> str:
    return f"{BOTLOCK_PREFIX}{external_chat_id}"


def record_from_update(update: dict) -> dict:
    """Map a Bot API message update to the buffer record BotApiConnector consumes."""
    msg = update["message"]
    frm = msg.get("from") or {}
    sent_at = dt.datetime.fromtimestamp(msg["date"], tz=dt.timezone.utc)
    return {
        "external_message_id": msg["message_id"],
        "sender_external_id": frm.get("id"),
        "sender_username": frm.get("username"),
        "sender_display_name": frm.get("first_name"),
        "text": msg.get("text"),
        "sent_at": sent_at.isoformat(),
        "raw": {"id": msg["message_id"], "reply_to": (msg.get("reply_to_message") or {}).get("message_id")},
        "message_type": "text",
        "attachments": [],
    }


def _default_is_configured(external_chat_id: int) -> bool:
    """Configure-before-capture gate (design §7). Canonical predicate: state.is_chat_configured."""
    from . import state

    return state.is_chat_configured(external_chat_id)


def ingest_message(
    external_chat_id: int,
    record: dict,
    *,
    debounce_seconds: int,
    is_configured=_default_is_configured,
) -> bool:
    """Buffer one inbound message and, debounced, enqueue one sync job. Returns True iff a job was enqueued."""
    if not is_configured(external_chat_id):
        return False  # configure-before-capture: drop pre-config chatter (design §7 GATE)
    queue.push_botbuf(external_chat_id, record)
    won_lock = get_redis().set(_botlock_key(external_chat_id), "1", nx=True, ex=debounce_seconds)
    if won_lock:
        queue.enqueue_sync(external_chat_id, trigger="manual")
        return True
    return False
