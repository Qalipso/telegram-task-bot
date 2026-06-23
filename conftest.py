"""Shared pytest fixtures (repo root): test-DB engine + isolated sessions.

Used by core, worker, and api test suites. Requires a reachable Postgres (aiwip_test).
"""
import os

# Tests must hit LOCAL services regardless of a developer .env (which points DATABASE_URL/REDIS_URL
# at the docker-compose hostnames "postgres"/"redis"). Env vars take precedence over .env in
# pydantic-settings, so set these before aiwip_core.config is first imported below.
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://aiwip:aiwip@localhost:5432/aiwip")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from aiwip_core import models  # noqa: F401,E402 — register tables on Base.metadata
from aiwip_core.db import Base  # noqa: E402

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://aiwip:aiwip@localhost:5432/aiwip_test"
)


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(TEST_DB_URL, future=True)
    with eng.begin() as conn:
        conn.exec_driver_sql("DROP SCHEMA public CASCADE")
        conn.exec_driver_sql("CREATE SCHEMA public")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    """Isolated session: create_savepoint so endpoint/service commit()s stay rolled back."""
    conn = engine.connect()
    trans = conn.begin()
    sess = Session(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint")
    try:
        yield sess
    finally:
        sess.close()
        if trans.is_active:
            trans.rollback()
        conn.close()


@pytest.fixture
def session(db):
    """Backwards-compatible alias for the ORM tests."""
    return db
