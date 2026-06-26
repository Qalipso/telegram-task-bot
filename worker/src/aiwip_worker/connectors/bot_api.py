"""Bot API connector: drains the Redis ingest buffer the bot fills (forward-only).

The bot service RPUSHes raw inbound records to aiwip:botbuf:{chat}; this connector drains that
list, returns them as FetchedMessages in ascending external_message_id order, and lets the
EXISTING run_sync path dedup + persist them. No history pull, no network — the bot already
captured everything forward-only.
"""
from __future__ import annotations

import datetime as dt
import json

from aiwip_core import queue
from aiwip_core.redis_client import get_redis

from .base import FetchedAttachment, FetchedMessage


def _parse_sent_at(value) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return value
    return dt.datetime.fromisoformat(value)


class BotApiConnector:
    def fetch_messages(
        self, chat_external_id: int, after_message_id: int | None = None, limit: int = 200
    ) -> list[FetchedMessage]:
        key = queue.botbuf_key(chat_external_id)
        r = get_redis()
        raw = r.lrange(key, 0, -1)
        r.delete(key)  # drain: this buffer is forward-only, never re-read
        records = [json.loads(x) for x in raw]
        records.sort(key=lambda rec: rec["external_message_id"])
        out: list[FetchedMessage] = []
        for rec in records:
            mid = rec["external_message_id"]
            if after_message_id is not None and mid <= after_message_id:
                continue
            out.append(
                FetchedMessage(
                    external_message_id=mid,
                    sender_external_id=rec.get("sender_external_id"),
                    sender_username=rec.get("sender_username"),
                    sender_display_name=rec.get("sender_display_name"),
                    text=rec.get("text"),
                    sent_at=_parse_sent_at(rec["sent_at"]),
                    raw=rec.get("raw", {}),
                    message_type=rec.get("message_type", "text"),
                    attachments=[
                        FetchedAttachment(
                            attachment_type=a["attachment_type"],
                            file_name=a.get("file_name"),
                            mime_type=a.get("mime_type"),
                        )
                        for a in rec.get("attachments", [])
                    ],
                )
            )
            if len(out) >= limit:
                break
        return out
