"""Phase 6 — get_or_create_chat can resolve/create a telegram_bot chat (default stays telegram)."""
from aiwip_core import models as m
from aiwip_worker import consumer


def test_creates_bot_chat_with_bot_connector_type(db):
    chat = consumer.get_or_create_chat(db, 9100, connector_type=m.ConnectorType.telegram_bot)
    assert chat.connector_type == m.ConnectorType.telegram_bot


def test_default_remains_telegram(db):
    chat = consumer.get_or_create_chat(db, 9101)
    assert chat.connector_type == m.ConnectorType.telegram
