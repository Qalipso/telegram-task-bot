"""One-shot LIVE sync of a Telegram chat into the database (manual-sync CLI).

Requires TELEGRAM_API_ID/HASH/SESSION in .env (mint with telegram_login.py) and a chat id.

    # chat id from .env TELEGRAM_CHAT_ID:
    .venv/bin/python scripts/sync_once.py
    # or explicit:
    .venv/bin/python scripts/sync_once.py <chat_id>

On the host, point DB/Redis at localhost (the .env values target docker hostnames):
    DATABASE_URL=postgresql+psycopg://aiwip:aiwip@localhost:5432/aiwip \\
    REDIS_URL=redis://localhost:6379/0 \\
    .venv/bin/python scripts/sync_once.py
"""
from __future__ import annotations

import sys

from sqlalchemy import select

from aiwip_core.config import settings
from aiwip_core.db import get_sessionmaker
from aiwip_core.models import Chat, ConnectorType, Message, SyncTriggerType
from aiwip_worker import sync
from aiwip_worker.connectors.telegram import TelegramConnector


def main() -> None:
    chat_id = int(sys.argv[1]) if len(sys.argv) > 1 else settings.telegram_chat_id
    if chat_id is None:
        raise SystemExit("Provide a chat id argument or set TELEGRAM_CHAT_ID in .env.")

    connector = TelegramConnector()
    with get_sessionmaker()() as db:
        chat = db.execute(
            select(Chat).where(
                Chat.connector_type == ConnectorType.telegram, Chat.external_chat_id == chat_id
            )
        ).scalar_one_or_none()
        if chat is None:
            chat = Chat(connector_type=ConnectorType.telegram, external_chat_id=chat_id, title=f"chat {chat_id}")
            db.add(chat)
            db.commit()

        run = sync.run_sync(db, connector, chat, SyncTriggerType.manual)
        print(f"sync {run.status.value}: read={run.messages_read} saved={run.messages_saved} err={run.error_message}")

        recent = db.execute(
            select(Message).where(Message.chat_id == chat.id).order_by(Message.external_message_id.desc()).limit(5)
        ).scalars().all()
        print(f"latest stored messages ({len(recent)} shown):")
        for msg in recent:
            text = (msg.text_content or "").replace("\n", " ")[:70]
            print(f"  #{msg.external_message_id} @{msg.sender_username or msg.sender_external_id}: {text}")


if __name__ == "__main__":
    main()
