"""Admin-only assignee management (the finite list the AI resolver matches against)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from aiwip_api import auth
from aiwip_api.schemas import AssigneeOut, CreateAssigneeRequest, UpdateAssigneeRequest
from aiwip_core.models import Assignee, User

router = APIRouter(prefix="/api/assignees", tags=["assignees"])


@router.get("", response_model=list[AssigneeOut])
def list_assignees(
    active: bool | None = None,
    _admin: User = Depends(auth.require_admin),
    db: Session = Depends(auth.get_db),
):
    query = select(Assignee).order_by(Assignee.id)
    if active is not None:
        query = query.where(Assignee.is_active.is_(active))
    return db.execute(query).scalars().all()


@router.post("", response_model=AssigneeOut, status_code=status.HTTP_201_CREATED)
def create_assignee(
    payload: CreateAssigneeRequest,
    _admin: User = Depends(auth.require_admin),
    db: Session = Depends(auth.get_db),
) -> Assignee:
    assignee = Assignee(
        display_name=payload.display_name,
        telegram_user_id=payload.telegram_user_id,
        telegram_username=payload.telegram_username,
        aliases=payload.aliases,
        user_id=payload.user_id,
        is_active=payload.is_active,
    )
    db.add(assignee)
    db.commit()
    db.refresh(assignee)
    return assignee


@router.patch("/{assignee_id}", response_model=AssigneeOut)
def update_assignee(
    assignee_id: int,
    payload: UpdateAssigneeRequest,
    _admin: User = Depends(auth.require_admin),
    db: Session = Depends(auth.get_db),
) -> Assignee:
    assignee = db.get(Assignee, assignee_id)
    if assignee is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignee not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(assignee, field, value)
    db.commit()
    db.refresh(assignee)
    return assignee
