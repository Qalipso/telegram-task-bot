"""Seed the first admin user.

Usage (against the configured DATABASE_URL):
    ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=... python -m aiwip_api.seed
"""
from __future__ import annotations

import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from aiwip_api import auth
from aiwip_core.db import get_sessionmaker
from aiwip_core.models import User, UserRole


def ensure_admin(db: Session, email: str, password: str, display_name: str = "Admin") -> User:
    """Create the admin if absent; return the existing one otherwise (idempotent)."""
    existing = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if existing is not None:
        return existing
    user = User(
        email=email,
        display_name=display_name,
        role=UserRole.admin,
        password_hash=auth.hash_password(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def main() -> None:
    email = os.environ.get("ADMIN_EMAIL")
    password = os.environ.get("ADMIN_PASSWORD")
    if not email or not password:
        raise SystemExit("Set ADMIN_EMAIL and ADMIN_PASSWORD to seed the first admin.")
    with get_sessionmaker()() as db:
        user = ensure_admin(db, email, password)
        print(f"admin ready: {user.email} (id={user.id})")


if __name__ == "__main__":
    main()
