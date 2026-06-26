"""Digest coalescing, quiet-hours, and one-message-per-cycle rendering (design spec §6.2).

MANDATORY in MVP (not a fast-follow): a burst of N new candidates in one cycle is coalesced into a
SINGLE digest message per chat. There is NO "Approve all" — the digest batches the PROMPT only;
each approval remains one human tap → one POST /approve.
"""
from __future__ import annotations

import datetime as dt

from aiwip_core.redis_client import get_redis

from aiwip_bot import cards, state

# Intra-cycle coalesce buffer (a Redis list of candidate ids awaiting the next digest emit).
DIGEST_KEY = "aiwip:botdigest:{chat}"
_DIGEST_TTL_SECONDS = 24 * 3600  # safety expiry so an orphaned buffer cannot leak forever


def _key(chat_id: int) -> str:
    return DIGEST_KEY.format(chat=chat_id)


def stage_candidate(chat_id: int, candidate_id: int) -> None:
    """Append a new candidate id to this chat's pending-digest buffer (dedup happens at drain)."""
    r = get_redis()
    r.rpush(_key(chat_id), candidate_id)
    r.expire(_key(chat_id), _DIGEST_TTL_SECONDS)


def drain_staged(chat_id: int) -> list[int]:
    """Atomically read-and-clear the buffer; return unique ids in first-seen order."""
    r = get_redis()
    key = _key(chat_id)
    pipe = r.pipeline()
    pipe.lrange(key, 0, -1)
    pipe.delete(key)
    raw, _ = pipe.execute()
    seen: set[int] = set()
    ordered: list[int] = []
    for value in raw:
        cid = int(value)
        if cid not in seen:
            seen.add(cid)
            ordered.append(cid)
    return ordered


def in_quiet_hours(now_utc: dt.time, start: int, end: int, enabled: bool = True) -> bool:
    """True if `now_utc` (a UTC time-of-day) falls in the quiet window [start:00, end:00).

    start/end are UTC hours (0-23). Handles the wrap-around case where start > end (spans midnight).
    When enabled is False, it is never quiet. Quiet-hours default ON (§6.2)."""
    if not enabled:
        return False
    hour = now_utc.hour
    if start == end:
        return False  # zero-width window
    if start < end:
        return start <= hour < end
    # wrap-around (e.g. 22 -> 7): quiet if at/after start OR before end
    return hour >= start or hour < end


def _is_ready(candidate: dict) -> bool:
    return (
        candidate.get("status") == "new"
        and not (candidate.get("missing_fields") or [])
        and (candidate.get("assignee_count") or 0) == 1
        and not candidate.get("assignee_ambiguous")
    )


def build_digest(candidates: list[dict]) -> cards.CardMessage | None:
    """Coalesce a cycle's candidates into ONE digest message. Returns None for an empty cycle.

    No 'Approve all': each row targets ONE candidate so every approval stays a single human tap."""
    if not candidates:
        return None
    ready = [c for c in candidates if _is_ready(c)]
    need = [c for c in candidates if not _is_ready(c)]
    text = (
        f"📋 {len(candidates)} new: {len(ready)} ready · {len(need)} need input\n"
        "Tap a candidate to review it."
    )
    rows: list[list[cards.InlineButton]] = []
    for c in candidates:
        cid = int(c["id"])
        title = (c.get("title") or f"#{cid}")[:40]
        # "open" routes to the per-item card (single-item judgement; NOT a batch approve).
        rows.append([cards.InlineButton(text=f"{title}", callback_data=cards.encode_callback("open", cid))])
    return cards.CardMessage(candidate_id=0, text=text, reply_markup=cards.InlineKeyboardMarkup(inline_keyboard=rows))


def emit_cycle(chat_id: int, api) -> list[cards.CardMessage]:
    """Drain this chat's staged ids, skip any at-or-below the cross-cycle watermark, fetch the rest,
    and return AT MOST ONE digest message.

    Returns [] when nothing new is staged. Two anti-spam controls cooperate: the `botcard:` watermark
    (state.already_surfaced) prevents cross-cycle re-surfacing; the single-message guarantee here
    prevents intra-cycle fan-out. After building the digest the watermark advances to the highest id
    surfaced, so the same candidate is never surfaced twice."""
    ids = [cid for cid in drain_staged(chat_id) if not state.already_surfaced(chat_id, cid)]
    if not ids:
        return []
    candidates: list[dict] = []
    for cid in ids:
        envelope = api.get_candidate(cid)
        candidates.append(envelope["candidate"] if "candidate" in envelope else envelope)
    message = build_digest(candidates)
    if message is None:
        return []
    state.set_surfaced_watermark(chat_id, max(ids))  # advance the watermark past what we surfaced
    return [message]
