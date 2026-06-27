"""Admin-invite codes: a single-use code that, when redeemed by the bot, CREATES a new admin
user + assignee bound to the redeemer's Telegram id.

Distinct from telegram_link (which links an EXISTING user). Reuses the same single-use-code
(atomic GETDEL) + rate-limit primitives so brute-forcing codes is throttled. The code is the
secret AND the Redis key — no app-side string compare. Because a redeemed code grants admin,
codes are single-use and short-lived; treat the code as a credential.
"""
from __future__ import annotations

import secrets

from aiwip_core.redis_client import get_redis

INVITE_CODE_PREFIX = "invite:"
INVITE_CODE_TTL_SECONDS = 86400  # 24h — shared with a person, so longer than a link code
_INVITE_CODE_BYTES = 18          # secrets.token_urlsafe(18) -> 24 url-safe chars


def issue_invite_code(inviter_user_id: int, role: str = "admin") -> str:
    """Mint a single-use invite, storing the granted role + inviter id, with a 24h TTL."""
    code = secrets.token_urlsafe(_INVITE_CODE_BYTES)
    get_redis().set(
        INVITE_CODE_PREFIX + code, f"{role}:{inviter_user_id}", ex=INVITE_CODE_TTL_SECONDS
    )
    return code


def redeem_invite_code(code: str) -> tuple[str, int] | None:
    """Atomically consume ``code`` once. Returns (role, inviter_user_id), or None if
    absent/used/expired. Single-use guaranteed by GETDEL."""
    raw = get_redis().getdel(INVITE_CODE_PREFIX + code)
    if raw is None:
        return None
    text = raw.decode() if isinstance(raw, bytes) else raw
    role, _, inviter = text.partition(":")
    try:
        return role, int(inviter)
    except ValueError:
        return None
