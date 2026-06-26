"""Bot-side Redis state helpers (design spec §8).

Owns the cross-cycle re-surfacing watermark under the `botcard:` prefix: per chat, the highest
candidate id already surfaced to the human, so a later cycle never re-surfaces it. The sibling
`botuser:` (per-user prefs) prefix is reserved by §8 but not built until a consumer needs it.
"""
from __future__ import annotations

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
