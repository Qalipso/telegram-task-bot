"""Bot-side Redis state helpers (design spec §8).

Owns the cross-cycle re-surfacing watermark under the `botcard:` prefix: per chat, the highest
candidate id already surfaced to the human, so a later cycle never re-surfaces it. The sibling
`botuser:` (per-user prefs) prefix is reserved by §8 but not built until a consumer needs it.
"""
from __future__ import annotations

import json
from typing import Any

from aiwip_core.redis_client import get_redis

SURFACED_WATERMARK_KEY = "botcard:{chat}"


def _watermark_key(chat_id: int) -> str:
    return SURFACED_WATERMARK_KEY.format(chat=chat_id)


def get_surfaced_watermark(chat_id: int) -> int:
    """Highest candidate id already surfaced to this chat (0 if never surfaced)."""
    raw = get_redis().get(_watermark_key(chat_id))
    return int(raw) if raw is not None else 0


def set_surfaced_watermark(chat_id: int, candidate_id: int) -> None:
    """Advance the watermark to candidate_id. Monotonic: a lower id never lowers the mark."""
    current = get_surfaced_watermark(chat_id)
    if candidate_id > current:
        get_redis().set(_watermark_key(chat_id), candidate_id)


def already_surfaced(chat_id: int, candidate_id: int) -> bool:
    """True if candidate_id is at-or-below this chat's watermark (i.e. already surfaced)."""
    return candidate_id <= get_surfaced_watermark(chat_id)


# --- Phase 5: per-chat onboarding config (configure-before-capture, spec §7/§8) ---
# A chat is "configured" only once a destination is chosen and saved here. The ingest gate
# (Phase 6) calls is_chat_configured() before buffering any inbound message.
CHAT_CONFIG_PREFIX = "aiwip:botcfg:"


def chat_config_key(chat_id: int) -> str:
    """Redis key holding the per-chat onboarding config JSON."""
    return f"{CHAT_CONFIG_PREFIX}{chat_id}"


def get_chat_config(chat_id: int) -> dict[str, Any] | None:
    """Return the saved per-chat config dict, or None if the chat was never configured."""
    raw = get_redis().get(chat_config_key(chat_id))
    if raw is None:
        return None
    return json.loads(raw)


def is_chat_configured(chat_id: int) -> bool:
    """True only if a config exists for this chat AND its `configured` flag is True."""
    cfg = get_chat_config(chat_id)
    return bool(cfg) and cfg.get("configured") is True


def set_chat_config(
    chat_id: int,
    *,
    destination: str,
    surface_mode: str = "cards",
    debounce_seconds: int | None = None,
    quiet_hours: dict[str, Any] | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    """Persist the per-chat config and mark the chat configured. Returns the stored dict.

    Stored with no TTL — onboarding state must survive bot restarts (spec §7: capture begins only
    after the chat is configured, and stays configured)."""
    existing = get_chat_config(chat_id) or {}
    cfg: dict[str, Any] = {
        "destination": destination,
        "surface_mode": surface_mode,
        "debounce_seconds": debounce_seconds,
        "quiet_hours": quiet_hours,
        "configured": True,
        "title": title or existing.get("title"),  # preserve existing title if not provided
    }
    get_redis().set(chat_config_key(chat_id), json.dumps(cfg))
    return cfg


def clear_chat_config(chat_id: int) -> None:
    """Remove a chat's config (used when the bot is removed from a group, or to re-onboard)."""
    get_redis().delete(chat_config_key(chat_id))


# --- Admin panel: outbound webhook (/setwebhook) ---
ADMIN_WEBHOOK_KEY = "aiwip:admin:webhook"


def get_admin_webhook() -> str | None:
    raw = get_redis().get(ADMIN_WEBHOOK_KEY)
    if raw is None:
        return None
    return raw.decode() if isinstance(raw, bytes) else raw


def set_admin_webhook(url: str) -> None:
    get_redis().set(ADMIN_WEBHOOK_KEY, url)


def clear_admin_webhook() -> None:
    get_redis().delete(ADMIN_WEBHOOK_KEY)


# --- Admin panel: per-chat capture pause ---
_CHAT_PAUSED_PREFIX = "aiwip:botpause:"


def _pause_key(chat_id: int) -> str:
    return f"{_CHAT_PAUSED_PREFIX}{chat_id}"


def is_chat_paused(chat_id: int) -> bool:
    return bool(get_redis().exists(_pause_key(chat_id)))


def pause_chat(chat_id: int) -> None:
    get_redis().set(_pause_key(chat_id), "1")


def resume_chat(chat_id: int) -> None:
    get_redis().delete(_pause_key(chat_id))


# --- Admin panel: single live "control panel" message id (per DM chat) ---
# The admin panel is one transient message that always sits at the bottom: each navigation
# deletes the previous panel and posts a fresh one. Task cards + confirmations are NOT tracked
# here, so they persist in the chat. TTL'd so a stale id can't linger forever.
_PANEL_PREFIX = "aiwip:botpanel:"
_PANEL_TTL_SECONDS = 86400  # 1 day


def _panel_key(chat_id: int) -> str:
    return f"{_PANEL_PREFIX}{chat_id}"


def get_panel_message(chat_id: int) -> int | None:
    raw = get_redis().get(_panel_key(chat_id))
    if raw is None:
        return None
    try:
        return int(raw)
    except (ValueError, TypeError):
        return None


def set_panel_message(chat_id: int, message_id: int) -> None:
    get_redis().set(_panel_key(chat_id), message_id, ex=_PANEL_TTL_SECONDS)


def clear_panel_message(chat_id: int) -> None:
    get_redis().delete(_panel_key(chat_id))


def list_configured_chats() -> list[int]:
    """Return external chat IDs that have an onboarding config key."""
    r = get_redis()
    ids: list[int] = []
    for key in r.scan_iter(f"{CHAT_CONFIG_PREFIX}*"):
        key_str = key.decode() if isinstance(key, bytes) else key
        try:
            ids.append(int(key_str.split(":")[-1]))
        except ValueError:
            pass
    return ids
