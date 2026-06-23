"""Assignee resolver foundation.

Matches a free-text mention (a name, @username, or alias) against the finite list of ACTIVE
assignees, case-insensitively. Returns all matches — the AI pipeline (Stage 8) treats 0 matches
as "needs review / unassigned" and >1 as "ambiguous". Exact normalized matching for MVP; fuzzy
matching is a later refinement.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from aiwip_core.models import Assignee


def _normalize(value: str) -> str:
    return value.strip().lstrip("@").lower()


def candidate_keys(assignee: Assignee) -> set[str]:
    keys: set[str] = set()
    if assignee.telegram_username:
        keys.add(_normalize(assignee.telegram_username))
    if assignee.display_name:
        keys.add(_normalize(assignee.display_name))
    for alias in assignee.aliases or []:
        keys.add(_normalize(str(alias)))
    return {k for k in keys if k}


def resolve_assignees(db: Session, mention: str) -> list[Assignee]:
    if not mention or not _normalize(mention):
        return []
    target = _normalize(mention)
    actives = db.execute(select(Assignee).where(Assignee.is_active.is_(True))).scalars().all()
    return [a for a in actives if target in candidate_keys(a)]
