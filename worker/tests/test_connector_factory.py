"""Phase 6 — connector factory keyed on Chat.connector_type (bot-only after the cutover)."""
import pytest

from aiwip_worker import consumer
from aiwip_worker.connectors.bot_api import BotApiConnector


def test_factory_returns_bot_connector_for_telegram_bot():
    assert isinstance(consumer.build_connector("telegram_bot"), BotApiConnector)


def test_factory_rejects_legacy_and_unknown_types():
    for bad in ("telegram", "slack"):
        with pytest.raises(ValueError):
            consumer.build_connector(bad)
