"""Phase 5 — configure-before-capture onboarding flow (spec §7)."""
from aiwip_bot import onboarding, state
from aiwip_core.redis_client import get_redis

CHAT = 5552002


def _clean(chat: int) -> None:
    get_redis().delete(state.chat_config_key(chat))


def test_added_to_unconfigured_group_returns_config_prompt():
    _clean(CHAT)
    prompt = onboarding.on_bot_added_to_group(CHAT)
    assert prompt is not None
    assert "text" in prompt and prompt["text"]
    actions = prompt["actions"]
    assert any(a["action"] == "choose_destination" for a in actions)
    _clean(CHAT)


def test_added_to_already_configured_group_returns_none():
    _clean(CHAT)
    state.set_chat_config(CHAT, destination="board:7")
    assert onboarding.on_bot_added_to_group(CHAT) is None
    _clean(CHAT)


def test_handle_destination_choice_saves_config_and_marks_configured():
    _clean(CHAT)
    result = onboarding.handle_destination_choice(CHAT, destination="board:99")
    assert result["configured"] is True
    assert result["destination"] == "board:99"
    assert state.is_chat_configured(CHAT) is True
    _clean(CHAT)


def test_removed_from_group_clears_config_and_closes_gate():
    # The "capture stops" half of the gate is verified in Phase 6 (which owns ingest.py); here we
    # assert the config (gate predicate) is cleared so a re-added chat must reconfigure first.
    chat2 = 5552099
    get_redis().delete(state.chat_config_key(chat2))
    state.set_chat_config(chat2, destination="board:5")
    assert state.is_chat_configured(chat2) is True
    onboarding.on_bot_removed_from_group(chat2)
    assert state.is_chat_configured(chat2) is False
    get_redis().delete(state.chat_config_key(chat2))
