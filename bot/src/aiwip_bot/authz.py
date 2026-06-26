"""Per-callback tapper authorization (design spec §6.4 — CRITICAL security gate).

The Telegram tapper's identity (callback.from_user.id) is mapped, AGAINST THE DATABASE, to a
platform User via the Assignee.telegram_user_id link, and admin is required. callback_data is
NEVER trusted to prove identity or permission; only this DB lookup decides.

Denied tappers get a calm "ask an admin" message — the bot never reveals whether the id is known.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from aiwip_core.models import Assignee, User, UserRole

_DENY_MESSAGE = "You are not authorized to do this. Please ask an admin."


@dataclass(frozen=True)
class AuthDecision:
    allowed: bool
    user_id: int | None = None
    reason: str = ""


def authorize_tapper(db: Session, telegram_user_id: int) -> AuthDecision:
    """Map a Telegram user id -> linked admin User. Allow only a linked admin.

    Returns AuthDecision(allowed, user_id, reason). `user_id` is populated even when denied
    (e.g. a linked non-admin) so the caller can audit, but `allowed` gates every action.
    """
    assignee = db.execute(
        select(Assignee).where(Assignee.telegram_user_id == telegram_user_id)
    ).scalars().first()
    if assignee is None or assignee.user_id is None:
        return AuthDecision(allowed=False, user_id=None, reason=_DENY_MESSAGE)

    user = db.get(User, assignee.user_id)
    if user is None:
        return AuthDecision(allowed=False, user_id=None, reason=_DENY_MESSAGE)
    if user.role != UserRole.admin:
        return AuthDecision(allowed=False, user_id=user.id, reason=_DENY_MESSAGE)

    return AuthDecision(allowed=True, user_id=user.id, reason="")
