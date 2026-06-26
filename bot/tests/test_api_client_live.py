"""Phase 3 — LIVE integration: bot logs in and GET /api/auth/me returns 200.

Skips cleanly when no API is reachable or no admin creds are configured, so CI
without an API still passes (the spec's "CI-safe mode"). To run locally, export
BOT_ADMIN_EMAIL / BOT_ADMIN_PASSWORD and start the API on localhost:8000.
"""
import os

import httpx
import pytest

from aiwip_bot.api_client import ApiClient

API_BASE = os.environ.get("BOT_API_BASE", "http://localhost:8000")
EMAIL = os.environ.get("BOT_ADMIN_EMAIL")
PASSWORD = os.environ.get("BOT_ADMIN_PASSWORD")


def _api_reachable() -> bool:
    try:
        httpx.get(f"{API_BASE}/health", timeout=1.0)
        return True
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(
    not (EMAIL and PASSWORD and _api_reachable()),
    reason="live API + BOT_ADMIN_EMAIL/PASSWORD not available (CI-safe skip)",
)


def test_bot_logs_in_and_me_returns_200():
    client = ApiClient(API_BASE, EMAIL, PASSWORD)
    try:
        client.login()   # POST /api/auth/login -> sets aiwip_session
        me = client.me()  # GET /api/auth/me -> 200 (cookie replayed)
        assert me.get("email") == EMAIL
    finally:
        client.close()
