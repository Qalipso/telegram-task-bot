"""Phase 5 — per-chat onboarding config stored in Redis (configure-before-capture)."""
from aiwip_bot import state
from aiwip_core.redis_client import get_redis

CHAT = 5551001


def _clean(chat: int) -> None:
    get_redis().delete(state.chat_config_key(chat))


def test_unconfigured_chat_reads_as_not_configured():
    _clean(CHAT)
    assert state.is_chat_configured(CHAT) is False
    assert state.get_chat_config(CHAT) is None


def test_set_config_marks_chat_configured_and_round_trips():
    _clean(CHAT)
    state.set_chat_config(CHAT, destination="board:42")
    assert state.is_chat_configured(CHAT) is True
    cfg = state.get_chat_config(CHAT)
    assert cfg is not None
    assert cfg["destination"] == "board:42"
    assert cfg["configured"] is True
    _clean(CHAT)
