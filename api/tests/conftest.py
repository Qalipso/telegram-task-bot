"""API-specific fixtures: a TestClient with get_db overridden to the test session.

The DB fixtures (`engine`, `db`) come from the repo-root conftest.
Sessions use the real local Redis (ephemeral, TTL'd).
"""
import pytest
from fastapi.testclient import TestClient

from aiwip_api.auth import get_db
from aiwip_api.main import app


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
