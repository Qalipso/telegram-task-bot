"""API test fixtures: a test-DB-backed TestClient with the get_db dependency overridden.

Sessions use the real local Redis (ephemeral, TTL'd). DB uses aiwip_test with
transaction-rollback isolation per test.
"""
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from aiwip_core import models  # noqa: F401 — register tables
from aiwip_core.db import Base
from aiwip_api.auth import get_db
from aiwip_api.main import app

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://aiwip:aiwip@localhost:5432/aiwip_test"
)


@pytest.fixture(scope="session")
def _engine():
    eng = create_engine(TEST_DB_URL, future=True)
    with eng.begin() as conn:
        conn.exec_driver_sql("DROP SCHEMA public CASCADE")
        conn.exec_driver_sql("CREATE SCHEMA public")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(_engine):
    conn = _engine.connect()
    trans = conn.begin()
    # create_savepoint: endpoint-level commit() releases a SAVEPOINT, so the outer
    # transaction still rolls back for test isolation.
    sess = Session(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint")
    try:
        yield sess
    finally:
        sess.close()
        if trans.is_active:
            trans.rollback()
        conn.close()


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
