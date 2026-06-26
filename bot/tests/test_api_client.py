"""Phase 3 — api_client login + cookie replay + error mapping (no network)."""
import httpx
import pytest

from aiwip_bot.api_client import ApiClient, ConversationalApiError


def _client_with(handler) -> ApiClient:
    """Build an ApiClient whose httpx.Client uses a MockTransport handler."""
    transport = httpx.MockTransport(handler)
    return ApiClient(
        base_url="http://api:8000",
        email="admin@aiwip.local",
        password="pw",
        transport=transport,
    )


def test_login_then_me_returns_200_and_user():
    state = {"logged_in": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/login":
            state["logged_in"] = True
            return httpx.Response(
                200,
                json={"id": 1, "email": "admin@aiwip.local", "role": "admin"},
                headers={"set-cookie": "aiwip_session=tok123; Path=/; HttpOnly"},
            )
        if request.url.path == "/api/auth/me":
            # Prove the cookie was replayed.
            assert "aiwip_session=tok123" in request.headers.get("cookie", "")
            return httpx.Response(200, json={"id": 1, "email": "admin@aiwip.local", "role": "admin"})
        return httpx.Response(404)

    client = _client_with(handler)
    client.login()
    assert state["logged_in"] is True
    me = client.me()
    assert me["email"] == "admin@aiwip.local"


def test_me_triggers_login_once_when_not_logged_in():
    calls = {"login": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/login":
            calls["login"] += 1
            return httpx.Response(
                200, json={"id": 1}, headers={"set-cookie": "aiwip_session=t; Path=/"}
            )
        if request.url.path == "/api/auth/me":
            return httpx.Response(200, json={"id": 1})
        return httpx.Response(404)

    client = _client_with(handler)
    client.me()  # not logged in yet -> logs in lazily, then succeeds
    client.me()  # already has cookie -> no second login
    assert calls["login"] == 1


def test_login_with_bad_credentials_raises_conversational():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Invalid email or password"})

    client = _client_with(handler)
    with pytest.raises(ConversationalApiError) as exc:
        client.login()
    assert "credential" in str(exc.value).lower() or "login" in str(exc.value).lower()


def test_request_relogins_once_on_401():
    state = {"logins": 0, "me_calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/login":
            state["logins"] += 1
            return httpx.Response(
                200, json={"id": 1}, headers={"set-cookie": "aiwip_session=fresh; Path=/"}
            )
        if request.url.path == "/api/auth/me":
            state["me_calls"] += 1
            # First /me returns 401 (stale session); after re-login the retry returns 200.
            if state["me_calls"] == 1:
                return httpx.Response(401, json={"detail": "Invalid or expired session"})
            return httpx.Response(200, json={"id": 1})
        return httpx.Response(404)

    client = _client_with(handler)
    me = client.me()
    assert me["id"] == 1
    assert state["logins"] == 2    # initial login + one re-login
    assert state["me_calls"] == 2  # the 401 call + the retried call


def test_login_replays_secure_cookie_over_http():
    """A Secure cookie (the API sets secure=True per §6.4) is dropped by httpx's jar over plain
    http, so the client must parse the token from Set-Cookie and replay it as an explicit Cookie
    header — otherwise every bot↔API call over http://api:8000 401s."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/login":
            return httpx.Response(
                200, json={"id": 1},
                headers={"set-cookie": "aiwip_session=sec123; Path=/; Secure; HttpOnly"},
            )
        if request.url.path == "/api/auth/me":
            seen["cookie"] = request.headers.get("cookie", "")
            return httpx.Response(200, json={"id": 1})
        return httpx.Response(404)

    client = _client_with(handler)
    client.me()
    assert "aiwip_session=sec123" in seen["cookie"]
    assert seen["cookie"].count("aiwip_session=") == 1  # exactly one (no jar+explicit duplicate)
