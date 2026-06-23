"""Auth endpoints: login / logout / me."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from aiwip_api import auth
from aiwip_api.schemas import LoginRequest, UserOut
from aiwip_core.models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=UserOut)
def login(payload: LoginRequest, response: Response, db: Session = Depends(auth.get_db)) -> User:
    user = db.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()
    if user is None or not auth.verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    token = auth.create_session(user.id)
    response.set_cookie(
        auth.COOKIE_NAME, token, httponly=True, samesite="lax", max_age=auth.SESSION_TTL_SECONDS
    )
    return user


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(auth.COOKIE_NAME)
    if token:
        auth.destroy_session(token)
    response.delete_cookie(auth.COOKIE_NAME)
    return {"status": "logged_out"}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(auth.get_current_user)) -> User:
    return user
