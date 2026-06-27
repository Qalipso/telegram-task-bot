"""aiwip_bot.onboarding — configure-before-capture flow (design spec §7).

When the bot is added to a group it must first ask which board/destination to log tasks into,
and only after a destination is saved does capture begin (the ingest gate, Phase 6, checks
state.is_chat_configured). This module is pure data-in/data-out: it decides *what* to prompt and
*what* to persist; the Phase-4 sender renders the returned dict into a message + inline keyboard.
Keeping it I/O-free makes the gate testable against Redis alone.
"""
from __future__ import annotations

from typing import Any

from . import state

# User-facing onboarding copy (spec §7 wording).
CONFIG_PROMPT_TEXT = "Чтобы я начал ловить задачи, выберите куда их складывать."
DEST_OPTIONS_TEXT = "Куда отправлять подтверждённые задачи?"

# Stable callback prefixes — telegram_app matches on these.
DEST_PREFIX = "dest:"
DEST_INTERNAL = "dest:internal"
DEST_TRELLO = "dest:trello"
DEST_NOTION = "dest:notion"
DEST_WEBHOOK = "dest:webhook"


def destination_options() -> dict[str, Any]:
    """Second-step menu: pick where approved tasks land (shown after the first button tap)."""
    return {
        "text": DEST_OPTIONS_TEXT,
        "actions": [
            {"action": DEST_INTERNAL, "label": "Только в боте (сейчас)"},
            {"action": DEST_TRELLO,   "label": "Trello (скоро)"},
            {"action": DEST_NOTION,   "label": "Notion (скоро)"},
            {"action": DEST_WEBHOOK,  "label": "Webhook / Zapier (скоро)"},
        ],
    }


def on_bot_added_to_group(chat_id: int) -> dict[str, Any] | None:
    """Return the config prompt for an unconfigured chat, or None if already configured.

    The returned dict shape (rendered by the Phase-4 sender):
        {"text": str, "actions": [{"action": "choose_destination", "label": str}, ...]}
    Returning None means the chat is already configured — do NOT re-prompt.
    """
    if state.is_chat_configured(chat_id):
        return None
    return {
        "text": CONFIG_PROMPT_TEXT,
        "actions": [
            {"action": "choose_destination", "label": "Выбрать борду/назначение"},
        ],
    }


def handle_destination_choice(chat_id: int, *, destination: str, title: str | None = None) -> dict[str, Any]:
    """Persist the chosen destination, mark the chat configured, and return the stored config.

    After this returns, `state.is_chat_configured(chat_id)` is True and capture may begin
    (the Phase-6 ingest gate starts pushing inbound messages to the extract buffer).
    """
    return state.set_chat_config(chat_id, destination=destination, title=title)


def on_bot_removed_from_group(chat_id: int) -> None:
    """Clear a chat's config when the bot is removed (or to re-onboard).

    Closes the configure-before-capture gate again: until the chat is reconfigured, inbound
    messages capture nothing. Honors team-consent reversibility (spec §6.3, §13).
    """
    state.clear_chat_config(chat_id)
