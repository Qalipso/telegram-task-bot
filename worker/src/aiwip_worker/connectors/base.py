"""Connector interface + the normalized message shape the sync engine consumes."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class FetchedMessage:
    external_message_id: int
    sender_external_id: int | None
    sender_username: str | None
    sender_display_name: str | None
    text: str | None
    sent_at: dt.datetime
    raw: dict = field(default_factory=dict)


@runtime_checkable
class Connector(Protocol):
    """A communication source. MVP: Telegram (Telethon). Future: Slack/Email/etc."""

    def fetch_messages(
        self, chat_external_id: int, after_message_id: int | None = None, limit: int = 200
    ) -> list[FetchedMessage]:
        """Return messages with id > after_message_id, ascending, capped at `limit`."""
        ...
