"""Authentication: bcrypt password hashing + Redis-backed server-side sessions (D5).

Sessions are opaque random tokens stored in Redis (TTL), referenced by an httpOnly cookie.
FastAPI dependencies enforce authentication and the admin role.
"""
from __future__ import annotations

import secrets
from collections.abc import Iterator

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from aiwip_core.db import get_sessionmaker
from aiwip_core.models import User, UserRole
from aiwip_core.redis_client import get_redis

COOKIE_NAME = "aiwip_session"
SESSION_PREFIX = "session:"
SESSION_TTL_SECONDS = 7 * 24 * 3600
_BCRYPT_MAX_BYTES = 72  # bcrypt truncates/raises beyond this; normalize for consistency


def _encode(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_encode(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(_encode(password), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    get_redis().set(SESSION_PREFIX + token, str(user_id), ex=SESSION_TTL_SECONDS)
    return token


def get_session_user_id(token: str) -> int | None:
    raw = get_redis().get(SESSION_PREFIX + token)
    return int(raw) if raw is not None else None


def destroy_session(token: str) -> None:
    get_redis().delete(SESSION_PREFIX + token)


def get_db() -> Iterator[Session]:
    with get_sessionmaker()() as session:
        yield session


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    user_id = get_session_user_id(token)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User no longer exists")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin role required")
    return user
