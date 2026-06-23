"""SQLAlchemy engine/session factory and the declarative Base.

Sync SQLAlchemy is used throughout: at the target scale (~500 messages/day,
system-spec §24) async DB access adds complexity without benefit, and FastAPI
runs sync endpoints in a threadpool. (Build decision build-D2.)
"""
from __future__ import annotations

from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models (populated from Stage 2 onward)."""


@lru_cache
def get_engine() -> Engine:
    return create_engine(settings.database_url, pool_pre_ping=True, future=True)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
