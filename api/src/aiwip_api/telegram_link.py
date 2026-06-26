"""Telegram account-linking: single-use link codes + a from-scratch Redis rate limiter.

Security-critical (design spec §6.4). Two pieces live here so the route stays thin:

1. Link codes: an admin (already authenticated) requests a one-time code, server-bound to
   THEIR user id, stored under the NEW prefix ``tglink:`` with a short TTL. The bot redeems it
   once (atomic GETDEL). The code proves WHICH platform user is linking; the client-supplied
   ``telegram_user_id`` is data to write, NEVER identity (§6.4).

2. Rate limiter: there is NO rate limiting anywhere else in this repo. A plain fixed-window
   Redis counter, keyed independently by telegram_user_id and by client IP.
"""
from __future__ import annotations

import secrets

from aiwip_core.redis_client import get_redis

# --- link codes -------------------------------------------------------------
LINK_CODE_PREFIX = "tglink:"          # NEW prefix, distinct from auth.SESSION_PREFIX ("session:")
LINK_CODE_TTL_SECONDS = 300           # ~5 minutes (spec §6.4)
_LINK_CODE_BYTES = 32                 # secrets.token_urlsafe(32) -> 43 url-safe chars (~256 bits)

# --- rate limiter (built from scratch — none exists in the repo) ------------
RATE_LIMIT_TGUSER_PREFIX = "tglink:rl:tg:"
RATE_LIMIT_IP_PREFIX = "tglink:rl:ip:"
RATE_LIMIT_MAX_ATTEMPTS = 5           # attempts allowed per window, per key
RATE_LIMIT_WINDOW_SECONDS = 300       # fixed window length


def issue_link_code(user_id: int) -> str:
    """Mint a server-bound, single-use code for ``user_id`` and store it with a short TTL.

    Returns the opaque code string (given to the admin to DM the bot).
    """
    code = secrets.token_urlsafe(_LINK_CODE_BYTES)
    get_redis().set(LINK_CODE_PREFIX + code, str(user_id), ex=LINK_CODE_TTL_SECONDS)
    return code


def redeem_link_code(code: str) -> int | None:
    """Atomically consume ``code`` once. Returns the bound user id, or None if absent/used/expired.

    Single-use is guaranteed by GETDEL (atomic get-and-delete): a second redeem of the same code
    sees nil. The caller MUST treat the returned int as the identity, never any client input. The
    code itself is the secret and the Redis key, so there is no app-side string compare to time.
    """
    raw = get_redis().getdel(LINK_CODE_PREFIX + code)
    return int(raw) if raw is not None else None


def check_and_increment_rate_limit(key_suffix: str, prefix: str) -> bool:
    """Fixed-window counter. Returns True if the attempt is ALLOWED, False if the limit is hit.

    First attempt in a window sets the window TTL; subsequent attempts INCR it. Once the count
    exceeds RATE_LIMIT_MAX_ATTEMPTS, returns False (limit tripped).
    """
    r = get_redis()
    key = prefix + key_suffix
    count = r.incr(key)
    if count == 1:
        r.expire(key, RATE_LIMIT_WINDOW_SECONDS)
    return count <= RATE_LIMIT_MAX_ATTEMPTS
