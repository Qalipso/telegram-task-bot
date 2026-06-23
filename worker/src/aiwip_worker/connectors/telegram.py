"""Live Telegram connector (Telethon user session).

Reads history incrementally with iter_messages(min_id=...). Credentials come from settings
(TELEGRAM_API_ID/HASH/SESSION); mint the session string with scripts/telegram_login.py.
Telethon is imported lazily so the module can be imported without credentials (tests use FakeConnector).
"""
from __future__ import annotations

from aiwip_core.config import settings

from .base import FetchedAttachment, FetchedMessage


class TelegramConnector:
    def __init__(self, api_id=None, api_hash=None, session=None):
        self._api_id = api_id or settings.telegram_api_id
        self._api_hash = api_hash or settings.telegram_api_hash
        self._session = session or settings.telegram_session
        if not (self._api_id and self._api_hash and self._session):
            raise RuntimeError(
                "Telegram credentials missing — set TELEGRAM_API_ID / TELEGRAM_API_HASH / "
                "TELEGRAM_SESSION (mint with scripts/telegram_login.py)."
            )
        self._client = None

    def _ensure_client(self):
        if self._client is None:
            from telethon.sessions import StringSession
            from telethon.sync import TelegramClient

            self._client = TelegramClient(
                StringSession(self._session), int(self._api_id), self._api_hash
            )
            self._client.connect()
        return self._client

    def fetch_messages(
        self, chat_external_id: int, after_message_id: int | None = None, limit: int = 200
    ) -> list[FetchedMessage]:
        client = self._ensure_client()
        out: list[FetchedMessage] = []
        for msg in client.iter_messages(
            chat_external_id, min_id=after_message_id or 0, limit=limit, reverse=True
        ):
            sender = getattr(msg, "sender", None)
            message_type, attachments = self._detect_media(msg)
            out.append(
                FetchedMessage(
                    external_message_id=msg.id,
                    sender_external_id=getattr(msg, "sender_id", None),
                    sender_username=getattr(sender, "username", None),
                    sender_display_name=getattr(sender, "first_name", None),
                    text=(msg.message or None),
                    sent_at=msg.date,
                    raw={"id": msg.id, "reply_to": getattr(msg, "reply_to_msg_id", None)},
                    message_type=message_type,
                    attachments=attachments,
                )
            )
        return out

    @staticmethod
    def _detect_media(msg) -> tuple[str, list]:
        """Best-effort media metadata only — no download/processing (Stage 5 placeholders)."""
        if getattr(msg, "photo", None):
            return "image", [FetchedAttachment("image")]
        if getattr(msg, "voice", None):
            return "voice", [FetchedAttachment("voice")]
        if getattr(msg, "document", None):
            f = getattr(msg, "file", None)
            return "document", [
                FetchedAttachment("document", file_name=getattr(f, "name", None), mime_type=getattr(f, "mime_type", None))
            ]
        return "text", []
