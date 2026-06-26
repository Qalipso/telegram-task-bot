"""Auth endpoints: login / logout / me."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from aiwip_api import auth, telegram_link
from aiwip_api.schemas import (
    LoginRequest,
    TelegramLinkStartResponse,
    TelegramRedeemRequest,
    TelegramRedeemResponse,
    UserOut,
)
from aiwip_core.models import Assignee, User

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=UserOut)
def login(payload: LoginRequest, response: Response, db: Session = Depends(auth.get_db)) -> User:
    user = db.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()
    if user is None or not auth.verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    token = auth.create_session(user.id)
    response.set_cookie(
        auth.COOKIE_NAME, token, httponly=True, secure=True, samesite="lax",
        max_age=auth.SESSION_TTL_SECONDS,
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


@router.post("/telegram-link/start", response_model=TelegramLinkStartResponse)
def telegram_link_start(admin: User = Depends(auth.require_admin)) -> TelegramLinkStartResponse:
    """Admin-initiated: issue a single-use code bound to THIS admin's user id (spec §6.4)."""
    code = telegram_link.issue_link_code(admin.id)
    return TelegramLinkStartResponse(code=code, expires_in_seconds=telegram_link.LINK_CODE_TTL_SECONDS)


@router.post("/telegram/redeem", response_model=TelegramRedeemResponse)
def telegram_redeem(
    payload: TelegramRedeemRequest,
    request: Request,
    response: Response,
    db: Session = Depends(auth.get_db),
) -> TelegramRedeemResponse:
    """Bot-called, UNAUTHENTICATED. The single-use CODE proves which platform user is linking;
    the client-supplied telegram_user_id is written only AFTER the code is verified (spec §6.4)."""
    # 0) Rate-limit BEFORE touching the code, on BOTH axes (per telegram_user_id and per IP),
    #    so brute-forcing codes is throttled before any lookup.
    client_ip = request.client.host if request.client else "unknown"
    tg_ok = telegram_link.check_and_increment_rate_limit(
        str(payload.telegram_user_id), telegram_link.RATE_LIMIT_TGUSER_PREFIX
    )
    ip_ok = telegram_link.check_and_increment_rate_limit(
        client_ip, telegram_link.RATE_LIMIT_IP_PREFIX
    )
    if not (tg_ok and ip_ok):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many link attempts")
    # 1) Atomically consume the code. The bound user id is the ONLY identity we trust.
    user_id = telegram_link.redeem_link_code(payload.code)
    if user_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired link code")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired link code")
    # 2) The user must already have a User-linked Assignee. Never auto-create; never grant admin.
    assignee = db.execute(
        select(Assignee).where(Assignee.user_id == user.id)
    ).scalar_one_or_none()
    if assignee is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No linked assignee for this user — ask an admin to attach a User",
        )
    # 3) Write the verified telegram id, then mint a session via the EXISTING auth scheme.
    assignee.telegram_user_id = payload.telegram_user_id
    db.commit()
    token = auth.create_session(user.id)
    response.set_cookie(
        auth.COOKIE_NAME, token, httponly=True, secure=True, samesite="lax",
        max_age=auth.SESSION_TTL_SECONDS,
    )
    return TelegramRedeemResponse(status="linked")
