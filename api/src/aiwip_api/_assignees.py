"""Shared assignee-id validation for the candidate and work-item reassign paths.

Lives in the api layer (not core) because it raises HTTPException — keeping the
core domain package free of FastAPI. Both routers import this one source of truth.
"""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from aiwip_core.models import Assignee


def validate_active_assignee_ids(db: Session, assignee_ids: list[int]) -> None:
    """Raise 422 if any id is unknown, inactive, or duplicated (spec §6.1D). No-op for an empty list.

    Rejecting duplicates here turns a unique-constraint IntegrityError (HTTP 500) into a clean 422 on
    both the work-item reassign and candidate-edit paths."""
    if not assignee_ids:
        return
    if len(set(assignee_ids)) != len(assignee_ids):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Duplicate assignee id(s) are not allowed")
    active_ids = set(
        db.execute(
            select(Assignee.id).where(Assignee.id.in_(assignee_ids), Assignee.is_active.is_(True))
        ).scalars().all()
    )
    invalid = [aid for aid in assignee_ids if aid not in active_ids]
    if invalid:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Unknown or inactive assignee id(s): {invalid}",
        )
