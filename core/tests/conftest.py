"""DB fixtures for Stage 2+ ORM tests.

Uses a dedicated test database (default `aiwip_test`), reset to a clean public schema
once per session, then create_all from the models metadata. Each test runs in a
transaction that is rolled back for isolation.
"""
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from aiwip_core import models  # noqa: F401 — register tables on Base.metadata
from aiwip_core.db import Base

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
def session(engine):
    conn = engine.connect()
    trans = conn.begin()
    sess = Session(bind=conn, expire_on_commit=False)
    try:
        yield sess
    finally:
        sess.close()
        if trans.is_active:  # a failed flush (constraint test) may have already rolled back
            trans.rollback()
        conn.close()
