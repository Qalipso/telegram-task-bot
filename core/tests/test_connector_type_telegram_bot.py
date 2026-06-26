"""Phase 6 — ConnectorType gains telegram_bot."""
from aiwip_core.models import ConnectorType


def test_telegram_bot_member_exists():
    assert ConnectorType.telegram_bot.value == "telegram_bot"
