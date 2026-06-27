"""HTTP client to the platform API: login once, replay the aiwip_session cookie.

Design spec §10 ("login once, replay aiwip_session cookie; map 401 re-login,
409/404 conversationally"). The bot never touches the database — every read and
write goes through the existing FastAPI endpoints over this client.

Auth model (consumed, verified):
  POST /api/auth/login  -> sets cookie `aiwip_session` (api auth.COOKIE_NAME).
  GET  /api/auth/me     -> 200 with the user JSON when the cookie is valid.
The cookie is a pure bearer token (design spec §1 / §6.4); we hold exactly one
session per bot process and re-login transparently on 401.

NOTE: the session cookie is Secure (spec §6.4), so httpx's jar drops it over a plain-http hop.
We parse the token from the login Set-Cookie header and replay it as an explicit Cookie header on
every request (jar-independent). The server still issues Secure cookies, so prod/TLS/browser
behavior is unchanged.
"""
from __future__ import annotations

from typing import Any

import httpx

from aiwip_core.logging import get_logger

logger = get_logger("aiwip.bot.api_client")

COOKIE_NAME = "aiwip_session"


class ConversationalApiError(Exception):
    """An API failure rendered as a human-readable message for a Telegram reply.

    `message` is safe to show a user; `status_code` is the originating HTTP code
    (or None for transport/login errors).
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ApiClient:
    """Stateful client holding a single logged-in session (cookie jar)."""

    def __init__(
        self,
        base_url: str,
        email: str | None,
        password: str | None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._email = email
        self._password = password
        self._client = httpx.Client(base_url=base_url, transport=transport, timeout=timeout)
        self._logged_in = False
        self._auth_cookie: dict[str, str] = {}  # explicit Cookie replay (jar drops Secure-over-http)

    # -- session lifecycle -------------------------------------------------

    def login(self) -> None:
        """Authenticate once; httpx.Client stores the aiwip_session cookie."""
        if not self._email or not self._password:
            raise ConversationalApiError(
                "Bot is not configured with admin credentials; ask an operator to set "
                "BOT_ADMIN_EMAIL / BOT_ADMIN_PASSWORD.",
                status_code=None,
            )
        try:
            resp = self._client.post(
                "/api/auth/login",
                json={"email": self._email, "password": self._password},
            )
        except httpx.HTTPError as exc:  # transport-level failure
            raise ConversationalApiError(f"Could not reach the API: {exc}", status_code=None) from exc
        if resp.status_code == 401:
            raise ConversationalApiError(
                "Bot login failed — check the admin credentials.", status_code=401
            )
        if resp.status_code >= 400:
            raise ConversationalApiError(
                f"Bot login failed (HTTP {resp.status_code}).", status_code=resp.status_code
            )
        token = self._extract_session_token(resp)
        if not token:
            raise ConversationalApiError(
                "Login succeeded but no session cookie was returned.", status_code=None
            )
        self._auth_cookie = {COOKIE_NAME: token}
        self._client.cookies.clear()  # rely on explicit replay only; the jar drops Secure-over-http
        self._logged_in = True
        logger.info("bot logged in as %s", self._email)

    @staticmethod
    def _extract_session_token(resp: httpx.Response) -> str | None:
        # Parse the raw Set-Cookie header FIRST: httpx's jar refuses to store/return a Secure cookie
        # over a plain-http response (the internal bot↔API hop), so resp.cookies is empty for exactly
        # the case we must support. Fall back to the jar for a non-Secure cookie.
        for header in resp.headers.get_list("set-cookie"):
            for part in header.split(";"):
                name, sep, value = part.strip().partition("=")
                if sep and name == COOKIE_NAME and value:
                    return value
        return resp.cookies.get(COOKIE_NAME)

    def _ensure_logged_in(self) -> None:
        if not self._logged_in:
            self.login()

    # -- request helper with 401 re-login + conversational mapping ---------

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        self._ensure_logged_in()
        resp = self._client.request(method, path, **self._with_auth(kwargs))
        if resp.status_code == 401:
            # Session expired / invalidated — re-login once and retry.
            logger.info("session expired; re-logging in")
            self._logged_in = False
            self.login()
            resp = self._client.request(method, path, **self._with_auth(kwargs))
        self._raise_for_conversational(resp)
        return resp

    def _with_auth(self, kwargs: dict) -> dict:
        """Inject the session token as an explicit Cookie header (jar-independent replay)."""
        merged = dict(kwargs)
        headers = dict(merged.get("headers") or {})
        if self._auth_cookie:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self._auth_cookie.items())
        merged["headers"] = headers
        return merged

    @staticmethod
    def _raise_for_conversational(resp: httpx.Response) -> None:
        """Map 404/409/403 (and other 4xx/5xx) to human-readable Telegram replies."""
        if resp.status_code < 400:
            return
        if resp.status_code == 404:
            raise ConversationalApiError(
                "That item no longer exists — it may have been removed.", status_code=404
            )
        if resp.status_code == 409:
            raise ConversationalApiError(
                "That action was already taken — nothing to do.", status_code=409
            )
        if resp.status_code == 403:
            raise ConversationalApiError("You are not allowed to do that.", status_code=403)
        raise ConversationalApiError(
            f"The server returned an error (HTTP {resp.status_code}).", status_code=resp.status_code
        )

    # -- the readiness endpoint this phase needs ---------------------------

    def me(self) -> dict:
        """GET /api/auth/me — used as the bot's API-readiness probe."""
        return self._request("GET", "/api/auth/me").json()

    # -- candidate-action surface (canonical contract for Phase 4) ---------
    # These are the EXACT method names/signatures Phase 4's handlers (and its
    # FakeApiClient) depend on. They live here because Phase 3 owns ApiClient
    # and lands first (§14); Phase 4 reuses this client rather than building a
    # second one. Each returns parsed JSON; all route through _request so they
    # inherit 401 re-login and 409/404/403 conversational mapping.

    def get_candidate(self, candidate_id: int) -> dict:
        """GET /api/candidates/{id} — returns the {candidate, assignees, messages} envelope."""
        return self._request("GET", f"/api/candidates/{candidate_id}").json()

    def approve_candidate(self, candidate_id: int) -> dict:
        """POST /api/candidates/{id}/approve — promote to a WorkItem (admin-gated, audited)."""
        return self._request("POST", f"/api/candidates/{candidate_id}/approve").json()

    def reject_candidate(self, candidate_id: int) -> dict:
        """POST /api/candidates/{id}/reject — discard the candidate (admin-gated, audited)."""
        return self._request("POST", f"/api/candidates/{candidate_id}/reject").json()

    def patch_candidate(self, candidate_id: int, payload: dict) -> dict:
        """PATCH /api/candidates/{id} — edit fields (priority, due, assignee, …)."""
        return self._request("PATCH", f"/api/candidates/{candidate_id}", json=payload).json()

    def sync_chat(self, chat_id: int) -> dict:
        """POST /api/sync/run — enqueue a manual sync job for the given external chat id."""
        return self._request("POST", "/api/sync/run", json={"chat_id": chat_id}).json()

    def sync_status(self) -> dict:
        """GET /api/sync/status — per-chat last-sync state (keyed by external_chat_id)."""
        return self._request("GET", "/api/sync/status").json()

    def invite_start(self) -> dict:
        """POST /api/auth/invite/start — mint a single-use admin-invite code (admin-only)."""
        return self._request("POST", "/api/auth/invite/start").json()

    def list_candidates(
        self,
        status: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """GET /api/candidates — optionally filtered by status, newest first."""
        params: dict[str, Any] = {"limit": limit}
        if status is not None:
            params["status"] = status
        return self._request("GET", "/api/candidates", params=params).json()

    def list_work_items(self) -> list[dict]:
        """GET /api/work-items — all work items visible to the admin (approved candidates)."""
        return self._request("GET", "/api/work-items").json()

    def list_assignees(self, active: bool | None = True) -> list[dict]:
        """GET /api/assignees?active=… — recognized people. active=None lists ALL (incl. inactive)."""
        params = {} if active is None else {"active": "true" if active else "false"}
        return self._request("GET", "/api/assignees", params=params).json()

    def create_assignee(self, payload: dict) -> dict:
        """POST /api/assignees — register a new person the resolver can match (admin-only)."""
        return self._request("POST", "/api/assignees", json=payload).json()

    def update_assignee(self, assignee_id: int, payload: dict) -> dict:
        """PATCH /api/assignees/{id} — edit/activate/deactivate a person (admin-only)."""
        return self._request("PATCH", f"/api/assignees/{assignee_id}", json=payload).json()

    def close(self) -> None:
        self._client.close()
