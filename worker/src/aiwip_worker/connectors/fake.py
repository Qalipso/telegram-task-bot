"""In-memory connector for tests (no network)."""
from __future__ import annotations

from .base import FetchedMessage


class FakeConnector:
    def __init__(self, messages: dict[int, list[FetchedMessage]] | None = None):
        self._messages = messages or {}

    def fetch_messages(
        self, chat_external_id: int, after_message_id: int | None = None, limit: int = 200
    ) -> list[FetchedMessage]:
        msgs = sorted(
            self._messages.get(chat_external_id, []), key=lambda m: m.external_message_id
        )
        if after_message_id is not None:
            msgs = [m for m in msgs if m.external_message_id > after_message_id]
        return msgs[:limit]
