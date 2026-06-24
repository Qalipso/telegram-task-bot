"""Tag vocabulary management (admin-only)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from aiwip_api import auth
from aiwip_api.schemas import CreateLabelRequest, LabelOut
from aiwip_core.models import Label, User

router = APIRouter(prefix="/api/labels", tags=["labels"])


@router.get("", response_model=list[LabelOut])
def list_labels(_admin: User = Depends(auth.require_admin), db: Session = Depends(auth.get_db)):
    return db.execute(select(Label).order_by(Label.id)).scalars().all()


@router.post("", response_model=LabelOut, status_code=status.HTTP_201_CREATED)
def create_label(
    payload: CreateLabelRequest, _admin: User = Depends(auth.require_admin), db: Session = Depends(auth.get_db)
) -> Label:
    if db.execute(select(Label).where(Label.name == payload.name)).scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "Label already exists")
    label = Label(name=payload.name, color=payload.color)
    db.add(label)
    db.commit()
    db.refresh(label)
    return label
