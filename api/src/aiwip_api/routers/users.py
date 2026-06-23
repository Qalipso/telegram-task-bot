"""Admin-only user management (assignee management lands here in Stage 6)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from aiwip_api import auth
from aiwip_api.schemas import CreateUserRequest, UserOut
from aiwip_core.models import User

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(_admin: User = Depends(auth.require_admin), db: Session = Depends(auth.get_db)):
    return db.execute(select(User).order_by(User.id)).scalars().all()


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: CreateUserRequest,
    _admin: User = Depends(auth.require_admin),
    db: Session = Depends(auth.get_db),
) -> User:
    exists = db.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(
        email=payload.email,
        display_name=payload.display_name,
        role=payload.role,
        password_hash=auth.hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
