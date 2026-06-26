# Phase 3 — Bot service scaffold (6th docker service, api_client, login+cookie replay)

> Implements design spec §10 (the new `bot/` service skeleton) and the Phase-3 row of §14.
> Source of truth: `/Users/eduardshatalov/Documents/telegram-task-bot/docs/specs/2026-06-26-bot-first-capture-layer-design.md`.
>
> **Scope of THIS phase only.** Stand up the `bot/` Python package, its Docker image, and the
> 6th docker-compose service, plus the API client that logs in once and replays the
> `aiwip_session` cookie (with 401 re-login and 409/404 conversational mapping). It does **not**
> implement capture, cards, handlers, authz, onboarding, or digest — those are Phases 4–6.
>
> **Library choice (justified up front).** This phase introduces **`aiogram` (v3, asyncio)**, not
> `python-telegram-bot` (PTB). Rationale: the design (§4.2, §6.2) needs a single asyncio event
> loop that simultaneously (a) long-polls `getUpdates`, (b) reads `bot.notify` from Redis, and
> (c) runs per-chat debounce timers. aiogram v3 is asyncio-native, has a small dependency tree,
> and its `Bot`/`Dispatcher` split maps cleanly onto "poll loop + handlers" without PTB's heavier
> `Application`/job-queue layer. Either library satisfies the contract; aiogram is chosen for the
> lighter asyncio fit. In **this** phase aiogram is only declared as a dependency and used for the
> `Bot` token-validation entrypoint — the poll loop is wired minimally and the heavy handler work
> lands in Phase 4. The HTTP client to our own API is **`httpx`** (already a known dep in the repo,
> see `api/pyproject.toml:18`).

---

## Conventions for this phase (read once)

- **Repo root:** `/Users/eduardshatalov/Documents/telegram-task-bot` (all paths below are absolute).
- **Test runner:** `.venv/bin/python -m pytest` from the repo root. Root `pytest.ini` has
  `testpaths = core/tests api/tests worker/tests`; this phase **adds `bot/tests`** to that list
  (Task 3.2). Root `conftest.py` forces `DATABASE_URL`/`REDIS_URL` to `localhost`.
- **Prerequisite services for tests:** a local Postgres and Redis must be reachable on
  `localhost:5432` / `localhost:6379` (same as every other suite). The API-integration test
  (Task 3.9) additionally needs the API process running on `localhost:8000` — the task spells out
  exactly how to start it and how to skip cleanly in CI when it is absent (the spec's "CI-safe
  mode" requirement).
- **Editable installs:** the repo's `.venv` installs `core`/`api`/`worker` editable. This phase
  installs the new `bot` package editable too (Task 3.3 verify step).
- **Commits:** Conventional Commits. **Commit only when the user asks** — the per-task
  `commit:` line is the message to use *if/when* asked, not an instruction to commit now.
- **Stale-image gotcha (documented per the spec).** docker-compose builds an image; editing
  `bot/src/...` after a build does **not** change the running container. After any source edit
  rebuild: `docker compose build bot && docker compose up -d bot`. This is called out again in
  Task 3.11 and in the `.env.example` comment.

Each task is `Red → verify-fail → Green → verify-pass → commit`.

---

## Task 3.1 — Create the `bot` package skeleton (importable, versioned)

**Goal:** a `bot/` package mirroring `worker/` layout so the test suite can import `aiwip_bot`.

### Red — write the failing test

Create directory `/Users/eduardshatalov/Documents/telegram-task-bot/bot/tests/` and write
`/Users/eduardshatalov/Documents/telegram-task-bot/bot/tests/test_smoke.py`:

```python
"""Phase 3 — bot package smoke test (host-side, no network)."""
import aiwip_bot


def test_package_imports_and_has_version():
    assert aiwip_bot.__version__ == "0.1.0"
```

### Verify it fails for the right reason

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && \
  .venv/bin/python -m pytest bot/tests/test_smoke.py -q
```

Expected: collection error / `ModuleNotFoundError: No module named 'aiwip_bot'`. Exit code `≠ 0`.
(This is the correct failure: the package does not exist yet.)

### Green — create the package

Create `/Users/eduardshatalov/Documents/telegram-task-bot/bot/src/aiwip_bot/__init__.py`:

```python
"""Telegram Bot API service for the AI Work Intelligence Platform.

Bot-first capture & confirm layer (design spec §10). This package owns the
getUpdates long-poll loop and the confirm-loop UX; it never writes to the
database directly — all writes go through the existing API over httpx.
"""

__version__ = "0.1.0"
```

Create the package's `pyproject.toml` at
`/Users/eduardshatalov/Documents/telegram-task-bot/bot/pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "aiwip-bot"
version = "0.1.0"
description = "Telegram Bot API service (bot-first capture & confirm) for the AI Work Intelligence Platform."
requires-python = ">=3.12"
dependencies = [
    "aiwip-core",
    "aiogram>=3.4",
    "httpx>=0.27",
]

[project.optional-dependencies]
test = ["pytest>=8"]

[tool.setuptools.packages.find]
where = ["src"]
```

> Mirrors `worker/pyproject.toml` exactly in structure (build-system, `[project]`, `[tool.setuptools.packages.find] where = ["src"]`).

### Verify it passes

The package is not installed yet, so run the smoke test with `src` on the path to prove the
module is well-formed:

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && \
  PYTHONPATH=bot/src .venv/bin/python -m pytest bot/tests/test_smoke.py -q
```

Expected: `1 passed`. Exit code `0`.

**commit:** `feat: scaffold aiwip_bot package skeleton`

---

## Task 3.2 — Register `bot/tests` in pytest testpaths

**Goal:** `bot/tests` is discovered by the repo's standard `python -m pytest` run.

### Red — prove it is NOT discovered today

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && \
  .venv/bin/python -m pytest --collect-only -q 2>&1 | grep -c "bot/tests"
```

Expected output: `0` (bot tests are not in the default collection set). Treat any value `> 0` as
"already done — skip this task."

### Green — add `bot/tests` to testpaths

Edit `/Users/eduardshatalov/Documents/telegram-task-bot/pytest.ini`. Current line 2 reads:

```
testpaths = core/tests api/tests worker/tests
```

Change it to:

```
testpaths = core/tests api/tests worker/tests bot/tests
```

Leave every other line in `pytest.ini` unchanged.

### Verify it passes

The bot package is still not installed, so the default run will fail to import `aiwip_bot`.
That is expected and is fixed in Task 3.3. For *this* task, verify only that the path is now in
the collection set:

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && \
  .venv/bin/python -m pytest --collect-only -q 2>&1 | grep -c "bot/tests"
```

Expected output: a value `≥ 1`. (It reports an import error for `aiwip_bot`, which proves the
path is now being scanned.) Exit code may be `≠ 0` until Task 3.3 — that is acceptable for this
task only.

**commit:** `chore: add bot/tests to pytest testpaths`

---

## Task 3.3 — Install the bot package editable into the dev venv

**Goal:** `aiwip_bot` imports from the installed venv (not just via `PYTHONPATH`), so the standard
`python -m pytest` run from repo root collects and passes the smoke test.

### Red — prove it is not yet installed

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && \
  .venv/bin/python -c "import aiwip_bot; print(aiwip_bot.__file__)"
```

Expected: `ModuleNotFoundError: No module named 'aiwip_bot'`. Exit code `≠ 0`.

### Green — editable install

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && \
  .venv/bin/pip install -e ./bot
```

Expected tail: `Successfully installed aiwip-bot-0.1.0` (plus `aiogram`, `httpx`, and their
transitive deps if not already present). Exit code `0`.

### Verify it passes (now via the standard runner)

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && \
  .venv/bin/python -m pytest bot/tests/test_smoke.py -q
```

Expected: `1 passed`. Exit code `0`. (No `PYTHONPATH` override needed now.)

**commit:** `chore: editable-install aiwip-bot into dev venv`

---

## Task 3.4 — Bot config module (spec §10 config keys)

**Goal:** add `aiwip_bot.config` with exactly the config keys from spec §10, following the
`aiwip_core.config` pattern (pydantic-settings `BaseSettings`, `@lru_cache`, Optional secret).

Spec §10 names these new keys:
`TELEGRAM_BOT_TOKEN`, `BOT_API_BASE=http://api:8000`, `BOT_ADMIN_EMAIL`, `BOT_ADMIN_PASSWORD`,
`BOT_POLL_INTERVAL_SECONDS`, `BOT_DEBOUNCE_SECONDS`, `BOT_DIGEST_INTERVAL_SECONDS`,
`AUTO_BAND=0.90`, `REVIEW_BAND=0.60`, quiet-hours window.

> The existing `aiwip_core.config.Settings` (`core/src/aiwip_core/config.py:13-14`) uses
> `SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)` and a
> module-level `settings = get_settings()` with `@lru_cache`. We mirror that pattern in a
> bot-local settings class so the bot reads the same `.env` and ignores keys it does not own.

### Red — write the failing test

Write `/Users/eduardshatalov/Documents/telegram-task-bot/bot/tests/test_config.py`:

```python
"""Phase 3 — bot config keys (spec §10)."""
from aiwip_bot.config import BotSettings


def test_defaults_match_spec_section_10():
    s = BotSettings()
    # Secrets are Optional so the service can boot without them (CI-safe mode).
    assert s.telegram_bot_token is None
    assert s.bot_admin_email is None
    assert s.bot_admin_password is None
    # Non-secret defaults from spec §10.
    assert s.bot_api_base == "http://api:8000"
    assert s.bot_poll_interval_seconds == 30
    assert s.bot_debounce_seconds == 60
    assert s.bot_digest_interval_seconds == 300
    assert s.auto_band == 0.90
    assert s.review_band == 0.60
    assert s.quiet_hours_start_utc == 22
    assert s.quiet_hours_end_utc == 8
    assert s.quiet_hours_enabled is True


def test_env_override_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("BOT_API_BASE", "http://localhost:8000")
    # @lru_cache on the module-level accessor must not mask env in tests:
    from aiwip_bot import config as cfg
    cfg.get_bot_settings.cache_clear()
    s = cfg.get_bot_settings()
    assert s.telegram_bot_token == "123:abc"
    assert s.bot_api_base == "http://localhost:8000"
```

### Verify it fails for the right reason

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && \
  .venv/bin/python -m pytest bot/tests/test_config.py -q
```

Expected: `ModuleNotFoundError: No module named 'aiwip_bot.config'`. Exit code `≠ 0`.

### Green — create the config module

Write `/Users/eduardshatalov/Documents/telegram-task-bot/bot/src/aiwip_bot/config.py`:

```python
"""Bot service settings (design spec §10), loaded from environment / .env.

Mirrors aiwip_core.config: pydantic-settings BaseSettings + @lru_cache accessor.
Secrets (bot token, bot-admin credentials) are Optional so the container boots
without them — that is the CI-safe / no-token boot mode the spec requires. The
poll loop refuses to start the long-poll without a token (see main.py) but the
process still comes up and reports readiness.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # --- Telegram Bot API (spec §10) — Optional so the service boots token-less. ---
    telegram_bot_token: str | None = None

    # --- This service -> platform API (spec §10). ---
    bot_api_base: str = "http://api:8000"
    bot_admin_email: str | None = None
    bot_admin_password: str | None = None

    # --- Loop cadences (spec §10). ---
    bot_poll_interval_seconds: int = 30
    bot_debounce_seconds: int = 60
    bot_digest_interval_seconds: int = 300

    # --- Confidence bands (spec §6.2 / §10). ---
    auto_band: float = 0.90
    review_band: float = 0.60

    # --- Quiet hours (spec §6.2, UTC per decision D4). Default ON. ---
    quiet_hours_enabled: bool = True
    quiet_hours_start_utc: int = 22
    quiet_hours_end_utc: int = 8


@lru_cache
def get_bot_settings() -> BotSettings:
    return BotSettings()


bot_settings = get_bot_settings()
```

### Verify it passes

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && \
  .venv/bin/python -m pytest bot/tests/test_config.py -q
```

Expected: `2 passed`. Exit code `0`.

**commit:** `feat: bot config module with spec §10 keys`

---

## Task 3.5 — Add the bot config keys to `.env.example`

**Goal:** the env template documents every spec §10 key (secrets blank), so an operator can fill
real values, and the stale-image gotcha is recorded.

### Red — prove the keys are absent

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && \
  grep -c "TELEGRAM_BOT_TOKEN" .env.example
```

Expected output: `0`. (Any value `> 0` means it is already present — skip this task.)

### Green — append the bot block

The current `.env.example` ends (lines 24-32) with the Telegram (Telethon) and OpenAI blocks.
**Append** the following block to the end of
`/Users/eduardshatalov/Documents/telegram-task-bot/.env.example` (do not modify existing lines):

```bash
# --- Bot service (Phase 3 — Telegram Bot API, bot-first capture) ---
# Bot token from BotFather. Leave BLANK for token-less / CI-safe boot (no long-poll).
TELEGRAM_BOT_TOKEN=
# Where the bot reaches the platform API. In docker-compose this is the api hostname.
BOT_API_BASE=http://api:8000
# Bot-service admin login (the bot logs in once and replays the aiwip_session cookie).
# Treat as a top-tier secret: this is full admin API access (spec §13).
BOT_ADMIN_EMAIL=
BOT_ADMIN_PASSWORD=
# Loop cadences (seconds).
BOT_POLL_INTERVAL_SECONDS=30
BOT_DEBOUNCE_SECONDS=60
BOT_DIGEST_INTERVAL_SECONDS=300
# Confidence bands (spec §6.2).
AUTO_BAND=0.90
REVIEW_BAND=0.60
# Quiet hours (UTC, per decision D4). Default ON.
QUIET_HOURS_ENABLED=true
QUIET_HOURS_START_UTC=22
QUIET_HOURS_END_UTC=8
# NOTE: docker-compose runs a BUILT image — after editing bot/src/... rebuild:
#   docker compose build bot && docker compose up -d bot
```

### Verify it passes

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && \
  grep -c "TELEGRAM_BOT_TOKEN\|BOT_API_BASE\|BOT_ADMIN_EMAIL\|BOT_POLL_INTERVAL_SECONDS\|AUTO_BAND" .env.example
```

Expected output: `5`. Exit code `0`.

**commit:** `docs: add bot service keys to .env.example`

---

## Task 3.6 — `api_client`: login-once + replay `aiwip_session` cookie

**Goal:** `aiwip_bot.api_client.ApiClient` logs in once via `POST /api/auth/login` and replays the
returned `aiwip_session` cookie on subsequent requests, exposing `me()` → `GET /api/auth/me`.

> Contract being consumed (verified):
> - `POST /api/auth/login` accepts `{"email","password"}` and, on success, sets cookie
>   `aiwip_session` (`api/src/aiwip_api/routers/auth.py:15-24`; cookie name from
>   `api/src/aiwip_api/auth.py:19`). On bad credentials it returns **401**.
> - `GET /api/auth/me` returns **200** with the user JSON when the `aiwip_session` cookie is
>   valid (`api/src/aiwip_api/routers/auth.py:36-38`).
>
> We use a persistent `httpx.Client` so the cookie jar is reused automatically across calls.

### Red — write the failing test (no network; httpx MockTransport)

Write `/Users/eduardshatalov/Documents/telegram-task-bot/bot/tests/test_api_client.py`:

```python
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
```

### Verify it fails for the right reason

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && \
  .venv/bin/python -m pytest bot/tests/test_api_client.py -q
```

Expected: `ModuleNotFoundError: No module named 'aiwip_bot.api_client'`. Exit code `≠ 0`.

### Green — create the api_client module

Write `/Users/eduardshatalov/Documents/telegram-task-bot/bot/src/aiwip_bot/api_client.py`:

```python
"""HTTP client to the platform API: login once, replay the aiwip_session cookie.

Design spec §10 ("login once, replay aiwip_session cookie; map 401 re-login,
409/404 conversationally"). The bot never touches the database — every read and
write goes through the existing FastAPI endpoints over this client.

Auth model (consumed, verified):
  POST /api/auth/login  -> sets cookie `aiwip_session` (api auth.COOKIE_NAME).
  GET  /api/auth/me     -> 200 with the user JSON when the cookie is valid.
The cookie is a pure bearer token (design spec §1 / §6.4); we hold exactly one
session per bot process and re-login transparently on 401.
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
        if COOKIE_NAME not in self._client.cookies:
            raise ConversationalApiError(
                "Login succeeded but no session cookie was returned.", status_code=None
            )
        self._logged_in = True
        logger.info("bot logged in as %s", self._email)

    def _ensure_logged_in(self) -> None:
        if not self._logged_in:
            self.login()

    # -- request helper with 401 re-login + conversational mapping ---------

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        self._ensure_logged_in()
        resp = self._client.request(method, path, **kwargs)
        if resp.status_code == 401:
            # Session expired / invalidated — re-login once and retry.
            logger.info("session expired; re-logging in")
            self._logged_in = False
            self.login()
            resp = self._client.request(method, path, **kwargs)
        self._raise_for_conversational(resp)
        return resp

    @staticmethod
    def _raise_for_conversational(resp: httpx.Response) -> None:
        """Map 404/409 (and other 4xx/5xx) to human-readable Telegram replies."""
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

    def list_assignees(self, active: bool = True) -> list[dict]:
        """GET /api/assignees?active=… — assignee picker source for the 'assign' card."""
        return self._request("GET", "/api/assignees", params={"active": active}).json()

    def close(self) -> None:
        self._client.close()
```

### Verify it passes

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && \
  .venv/bin/python -m pytest bot/tests/test_api_client.py -q
```

Expected: `3 passed`. Exit code `0`.

**commit:** `feat: bot api_client login + aiwip_session cookie replay`

---

## Task 3.7 — `api_client`: 401 re-login on a protected call

**Goal:** prove the transparent re-login path (a 401 on a normal request triggers exactly one
re-login then a retry). This is a distinct behavior from "first call logs in," so it gets its own
RED test.

### Red — add the failing test

Append to `/Users/eduardshatalov/Documents/telegram-task-bot/bot/tests/test_api_client.py`:

```python
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
            # First /me after the initial login returns 401 (stale session);
            # after the re-login the retry returns 200.
            if state["me_calls"] == 1:
                return httpx.Response(401, json={"detail": "Invalid or expired session"})
            return httpx.Response(200, json={"id": 1})
        return httpx.Response(404)

    client = _client_with(handler)
    me = client.me()
    assert me["id"] == 1
    assert state["logins"] == 2   # initial login + one re-login
    assert state["me_calls"] == 2  # the 401 call + the retried call
```

### Verify it fails for the right reason

If Task 3.6's `_request` was implemented exactly as written, this test **passes immediately** —
the re-login is already built. To honor Red-first, run it and confirm: if it already passes, this
task is a no-op verification (record the green run). If you implemented `_request` differently and
it fails, the failure message will show `state["logins"] == 1` (no re-login) — fix `_request` to
match the Task 3.6 code.

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && \
  .venv/bin/python -m pytest bot/tests/test_api_client.py::test_request_relogins_once_on_401 -q
```

Expected when correct: `1 passed`. Exit code `0`.

### Verify the whole api_client suite

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && \
  .venv/bin/python -m pytest bot/tests/test_api_client.py -q
```

Expected: `4 passed`. Exit code `0`.

**commit:** `test: cover api_client 401 re-login path`

---

## Task 3.8 — `main`: token-less boot + readiness probe (CI-safe mode)

**Goal:** `aiwip_bot.main` exposes a `run_once()` readiness snapshot (mirrors
`aiwip_worker.main.run_once`) and a `run()` loop that **boots without a token** — when
`telegram_bot_token` is `None` it logs that long-poll is disabled and stays alive, instead of
crashing. This is the spec's "boots without a token in a CI-safe mode."

> Mirrors `worker/src/aiwip_worker/main.py:18-27`'s `run_once()` shape (Redis check via
> `aiwip_core.health`) and its `if __name__ == "__main__": run()` entrypoint.

### Red — write the failing test

Write `/Users/eduardshatalov/Documents/telegram-task-bot/bot/tests/test_main.py`:

```python
"""Phase 3 — bot main: readiness snapshot + token-less (CI-safe) boot."""
from aiwip_core import health

from aiwip_bot import config, main


def test_run_once_reports_redis_and_api_flags(monkeypatch):
    monkeypatch.setattr(health, "check_redis", lambda: health.CheckResult(True, "connected"))
    # API probe is injected so the test never hits the network.
    snapshot = main.run_once(api_probe=lambda: True)
    assert snapshot == {"redis": True, "api": True, "long_poll": False}


def test_run_once_api_down(monkeypatch):
    monkeypatch.setattr(health, "check_redis", lambda: health.CheckResult(True, "connected"))
    snapshot = main.run_once(api_probe=lambda: False)
    assert snapshot["api"] is False


def test_long_poll_enabled_flag_reflects_token(monkeypatch):
    monkeypatch.setattr(health, "check_redis", lambda: health.CheckResult(True, "connected"))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    config.get_bot_settings.cache_clear()
    snapshot = main.run_once(api_probe=lambda: True)
    assert snapshot["long_poll"] is True
    config.get_bot_settings.cache_clear()  # reset for other tests


def test_run_returns_immediately_without_token(monkeypatch):
    """Token-less boot must not raise and must not block (CI-safe mode)."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    config.get_bot_settings.cache_clear()
    monkeypatch.setattr(health, "check_redis", lambda: health.CheckResult(True, "connected"))
    # once=True makes run() do a single readiness pass and return (no infinite loop).
    main.run(once=True, api_probe=lambda: True)
    config.get_bot_settings.cache_clear()
```

### Verify it fails for the right reason

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && \
  .venv/bin/python -m pytest bot/tests/test_main.py -q
```

Expected: `ModuleNotFoundError: No module named 'aiwip_bot.main'`. Exit code `≠ 0`.

### Green — create the main module

Write `/Users/eduardshatalov/Documents/telegram-task-bot/bot/src/aiwip_bot/main.py`:

```python
"""Bot service entrypoint (design spec §10).

Phase 3 scope: the service must BOOT (token-less / CI-safe) and report readiness.
The full getUpdates long-poll loop, bot.notify consumption, debounce timers, and
the callback dispatch wiring (parse_callback → handle_* + the 'open'/'edit'
actions) are owned by a SINGLE later phase — Phase 4 (Confirm UX) — which builds
this same main.py into the running dispatcher. They are not split across phases.
Here run() either:
  * starts a minimal long-poll only when a token is configured, or
  * with no token, logs that long-poll is disabled and stays alive as a
    readiness-only process (so the container is healthy in CI / no-token envs).

run_once() mirrors aiwip_worker.main.run_once(): a connectivity snapshot.
"""
from __future__ import annotations

import time
from typing import Callable

from aiwip_core import health
from aiwip_core.logging import get_logger

from .api_client import ApiClient, ConversationalApiError
from .config import get_bot_settings

logger = get_logger("aiwip.bot")


def _default_api_probe() -> bool:
    """Probe API readiness via GET /api/auth/me (login + cookie replay)."""
    s = get_bot_settings()
    client = ApiClient(s.bot_api_base, s.bot_admin_email, s.bot_admin_password)
    try:
        client.me()
        return True
    except ConversationalApiError as exc:
        logger.warning("api probe failed: %s", exc.message)
        return False
    finally:
        client.close()


def run_once(api_probe: Callable[[], bool] = _default_api_probe) -> dict:
    """One readiness cycle. Returns {redis, api, long_poll}."""
    s = get_bot_settings()
    redis_ok = health.check_redis().ok
    api_ok = api_probe()
    long_poll = bool(s.telegram_bot_token)
    snapshot = {"redis": redis_ok, "api": api_ok, "long_poll": long_poll}
    if redis_ok and api_ok:
        logger.info("bot ready %s", snapshot)
    else:
        logger.warning("bot degraded %s", snapshot)
    return snapshot


def run(once: bool = False, api_probe: Callable[[], bool] = _default_api_probe) -> None:
    """Main loop.

    Phase 3: a readiness heartbeat. With a token configured the long-poll is
    started by Phase 4; here we only log intent so the no-token path is proven
    CI-safe. `once=True` runs a single readiness pass and returns (for tests).
    """
    s = get_bot_settings()
    if not s.telegram_bot_token:
        logger.info("TELEGRAM_BOT_TOKEN not set — long-poll disabled (CI-safe boot)")
    else:
        logger.info("TELEGRAM_BOT_TOKEN present — long-poll will start in Phase 4")

    while True:
        run_once(api_probe=api_probe)
        if once:
            return
        time.sleep(s.bot_poll_interval_seconds)


if __name__ == "__main__":
    run()
```

### Verify it passes

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && \
  .venv/bin/python -m pytest bot/tests/test_main.py -q
```

Expected: `4 passed`. Exit code `0`.

**commit:** `feat: bot main readiness probe + token-less CI-safe boot`

---

## Task 3.9 — RED integration test: bot logs in and `GET /api/auth/me` → 200 (live API, CI-safe skip)

**Goal:** the spec's headline RED test — "bot api_client logs in and `GET /api/auth/me` returns
200" — exercised against a **real running API**, but skipped cleanly when the API is not reachable
(so CI without an API still passes). This is the integration counterpart to the mocked Task 3.6.

> This test does not start the API itself — it uses one if present. To run it locally, start the
> API and seed an admin first (the repo already supports this; the commands are spelled out in the
> verify block). The test reads `BOT_ADMIN_EMAIL`/`BOT_ADMIN_PASSWORD` from the environment.

### Red — write the (skippable) integration test

Write `/Users/eduardshatalov/Documents/telegram-task-bot/bot/tests/test_api_client_live.py`:

```python
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
        client.login()              # POST /api/auth/login -> sets aiwip_session
        me = client.me()            # GET /api/auth/me -> 200 (cookie replayed)
        assert me.get("email") == EMAIL
    finally:
        client.close()
```

### Verify it "fails for the right reason" (CI-safe = skipped, not errored)

With no API running and no creds set, the test must be **skipped**, not failed:

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && \
  .venv/bin/python -m pytest bot/tests/test_api_client_live.py -q
```

Expected: `1 skipped` (reason printed with `-rs`). Exit code `0`. This proves the CI-safe gate
works — the suite stays green where no API exists.

### Verify it passes against a real API (manual, local)

Start the API + seed an admin, then run with creds. The repo seeds a dev admin via its standard
flow; use whatever admin you have (the memory notes a dev admin `admin@aiwip.local`):

```bash
# Terminal A — bring up postgres, redis, api (built image):
cd /Users/eduardshatalov/Documents/telegram-task-bot && \
  docker compose up -d postgres redis api

# Terminal B — run the live test with real creds:
cd /Users/eduardshatalov/Documents/telegram-task-bot && \
  BOT_API_BASE=http://localhost:8000 \
  BOT_ADMIN_EMAIL=admin@aiwip.local \
  BOT_ADMIN_PASSWORD='<the dev admin password>' \
  .venv/bin/python -m pytest bot/tests/test_api_client_live.py -q -rs
```

Expected: `1 passed`. Exit code `0`. (If creds are wrong you get `1 failed` with
`ConversationalApiError: Bot login failed — check the admin credentials.`)

**commit:** `test: live integration — bot login + /api/auth/me 200 (CI-safe skip)`

---

## Task 3.10 — `bot/Dockerfile` (two-stage, mirrors worker)

**Goal:** a production Dockerfile that builds `core` + `bot` from the repo-root context, runs as a
non-root user, no exposed port, `CMD python -m aiwip_bot.main`.

> Mirrors `worker/Dockerfile` exactly: two-stage Alpine build, `pip install --user ./core` then
> the service, copy `/root/.local` into the runtime stage, non-root `appuser`. The only
> difference vs worker is the package name and the final `CMD` module.

### Red — prove the Dockerfile is absent

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && \
  test -f bot/Dockerfile && echo PRESENT || echo MISSING
```

Expected output: `MISSING`. (Any `PRESENT` means it already exists — skip.)

### Green — create the Dockerfile

Write `/Users/eduardshatalov/Documents/telegram-task-bot/bot/Dockerfile`:

```dockerfile
# Build context = repo root (so the shared `core` package is available).
FROM python:3.12-alpine AS builder

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apk add --no-cache gcc musl-dev libffi-dev openssl-dev python3-dev

WORKDIR /tmp

COPY core ./core
RUN pip install --user --no-cache-dir ./core

COPY bot ./bot
RUN pip install --user --no-cache-dir ./bot

FROM python:3.12-alpine

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/home/appuser/.local/lib/python3.12/site-packages \
    PATH=/home/appuser/.local/bin:$PATH

RUN addgroup -g 1000 appuser && adduser -D -u 1000 -G appuser appuser

WORKDIR /app

COPY --from=builder --chown=appuser:appuser /root/.local /home/appuser/.local

USER appuser

# No EXPOSE: the bot uses long-poll getUpdates and reaches the API outbound only.
CMD ["python", "-m", "aiwip_bot.main"]
```

### Verify it builds

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && \
  docker build -f bot/Dockerfile -t aiwip-bot:phase3-check .
```

Expected tail: `naming to docker.io/library/aiwip-bot:phase3-check` (or
`writing image ... done`). Exit code `0`.

Then confirm the entrypoint imports and the no-token boot returns cleanly inside the image:

```bash
docker run --rm aiwip-bot:phase3-check \
  python -c "from aiwip_bot import main; main.run(once=True, api_probe=lambda: False); print('boot-ok')"
```

Expected: a log line plus `boot-ok` on the last line. Exit code `0`. (This proves token-less
CI-safe boot works in the built image — `api_probe=lambda: False` avoids needing a live API.)

**commit:** `feat: bot Dockerfile (two-stage, non-root, no exposed port)`

---

## Task 3.11 — 6th docker-compose service `bot`

**Goal:** add the `bot` service to `docker-compose.yml`: built image, `env_file: .env`,
`depends_on` api **and** redis healthy, resource limits, json-file logging, **no `ports:`**.

> Template = the existing `worker` block (`docker-compose.yml:81-107`). The `bot` block differs
> by: it also depends on `api: condition: service_healthy` (the bot calls the API), and it carries
> the same resource limits as worker. Like worker it has no `ports:`. The api healthcheck already
> exists (`docker-compose.yml:60-65`), so `service_healthy` on api is valid.

### Red — prove the service is absent

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && \
  docker compose config --services 2>/dev/null | grep -c '^bot$'
```

Expected output: `0`. (Any `1` means it already exists — skip.)

### Green — add the `bot` block

Edit `/Users/eduardshatalov/Documents/telegram-task-bot/docker-compose.yml`. Insert the following
block **after** the `worker:` service block (i.e. after its last line at column-4 indentation,
currently the `reservations` block ending around line 107) and **before** the `web:` service
(line 109). Keep two-space indentation consistent with the file:

```yaml
  bot:
    build:
      context: .
      dockerfile: bot/Dockerfile
    env_file: .env
    environment:
      DATABASE_URL: postgresql+psycopg://${POSTGRES_USER:-aiwip}:${POSTGRES_PASSWORD:-aiwip}@postgres:5432/${POSTGRES_DB:-aiwip}
      REDIS_URL: redis://redis:6379/0
      BOT_API_BASE: http://api:8000
    depends_on:
      api:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "5"
    deploy:
      resources:
        limits:
          cpus: "0.5"
          memory: 256M
        reservations:
          cpus: "0.25"
          memory: 128M
```

> No `ports:` (long-poll, no inbound). No `healthcheck:` — the bot has no listening socket to
> probe; readiness is logged via `run_once()` (spec §10's "no exposed port"). `depends_on api
> healthy` ensures the API is up before the bot tries its first login.

### Verify the compose file is valid and the service is recognized

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && \
  docker compose config --services
```

Expected: the list now includes `bot` (alongside `postgres`, `redis`, `api`, `worker`, `web`).
Exit code `0`.

Confirm `bot` has no published ports:

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && \
  docker compose config | python3 -c "import sys,yaml; d=yaml.safe_load(sys.stdin); print('ports' in d['services']['bot'])"
```

Expected output: `False`. Exit code `0`.

> **Stale-image gotcha (documented).** docker-compose runs the *built* image, not your working
> tree. After editing anything under `bot/src/...`, rebuild before the change takes effect:
> `docker compose build bot && docker compose up -d bot`. (Also recorded in `.env.example`,
> Task 3.5.)

**commit:** `feat: add 6th docker-compose service (bot)`

---

## Task 3.12 — Full-suite regression gate (baseline stays green)

**Goal:** the existing ~94–96-test suite plus the new bot tests all pass via the standard runner.
No existing test was touched, so the baseline must be unchanged.

### Verify (fresh, complete run — Iron Law §3.5)

Ensure local Postgres + Redis are up, then:

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && \
  .venv/bin/python -m pytest -q -rs
```

Expected:
- All previously-passing tests still pass (no regressions; this phase added files only).
- New: `bot/tests/test_smoke.py` (1), `test_config.py` (2), `test_api_client.py` (4),
  `test_main.py` (4) all pass.
- `bot/tests/test_api_client_live.py` shows `1 skipped` (no live API in CI) — reason printed by
  `-rs`.
- Summary line resembles `NN passed, 1 skipped` with **0 failed, 0 errored**. Exit code `0`.

If anything fails, do **not** claim completion — investigate per §3.4 (read the full trace,
reproduce, root-cause) before any fix.

**commit:** `test: phase-3 bot scaffold suite green`

---

## SELF-REVIEW checklist

**Spec coverage (§10 + §14 Phase-3 row):**
- [x] `bot/` package created, mirroring `worker/` layout — `__init__.py`, `pyproject.toml`,
      `src/aiwip_bot/`, `tests/` (Tasks 3.1, 3.3).
- [x] `config.py` with **every** spec §10 key: `TELEGRAM_BOT_TOKEN`, `BOT_API_BASE`,
      `BOT_ADMIN_EMAIL`, `BOT_ADMIN_PASSWORD`, `BOT_POLL_INTERVAL_SECONDS`,
      `BOT_DEBOUNCE_SECONDS`, `BOT_DIGEST_INTERVAL_SECONDS`, `AUTO_BAND`, `REVIEW_BAND`,
      quiet-hours window (Task 3.4) — and mirrored in `.env.example` (Task 3.5).
- [x] `api_client.py`: login once + replay `aiwip_session` cookie + 401 re-login +
      409/404 (and 403) conversational mapping (Tasks 3.6, 3.7).
- [x] `main.py` getUpdates long-poll loop **entrypoint** with token-less CI-safe boot; the full
      poll loop **and all callback dispatch wiring are owned by a single later phase — Phase 4
      (Confirm UX)**, not split across Phases 3/4/6. Phase 4 builds into this same `main.py`:
      (1) the aiogram getUpdates handler that calls `handlers.parse_callback(callback.data)` →
      dispatches to the matching `handle_*` with `telegram_user_id=callback.from_user.id` + a DB
      session (including the `open` and `edit` actions and `pick_callback` parsing); (2) the
      `bot.notify` consumer loop (`queue.dequeue_notify()` → `api.get_candidate(id)` →
      `cards.render_card` → send to the linked-admin chat); (3) the sender that renders
      `cards.CardMessage` / onboarding `{text, actions}` dicts to aiogram `InlineKeyboardMarkup`.
      Phase 3's heartbeat is the placeholder; Phase 6 (ingest) must NOT also write `main.py` —
      it only produces `ingest.py` and points at Phase 4 as the dispatch owner (Task 3.8).
- [x] 6th docker-compose service `bot`: `env_file:.env`, `depends_on api+redis healthy`,
      **no exposed port**, resource limits, json-file logging (Task 3.11).
- [x] `bot/Dockerfile` two-stage, non-root, repo-root context (Task 3.10).
- [x] RED test: bot api_client logs in and `GET /api/auth/me` → 200 (mocked Task 3.6 + live
      Task 3.9); bot boots without a token in CI-safe mode (Task 3.8 + Task 3.10 image check).
- [x] Stale-image rebuild gotcha documented (Task 3.5 `.env.example` + Task 3.11).
- [x] Library choice (aiogram vs PTB) made and justified (header).

**Zero placeholders:** every code block is complete and runnable; no `TBD`/`TODO`/"add
validation"/"handle edge cases"/"similar to Task N". The only deferrals are the *named* Phase-4–6
features (capture, cards, handlers, authz, onboarding, digest), explicitly out of this phase's
scope per spec §14.

**Type / name consistency with other phases:**
- Cookie name `aiwip_session` matches `api/src/aiwip_api/auth.py:19` (`COOKIE_NAME`) — consumed,
  not redefined behaviorally.
- API base default `http://api:8000` matches spec §10 and the api hostname in docker-compose.
- Config key names match spec §10 verbatim (UPPER_SNAKE in env → lower_snake pydantic fields,
  the same mapping `aiwip_core.config` uses).
- `ConversationalApiError` (signature `(message: str, status_code: int | None = None)`, attributes
  `.message` / `.status_code`) is the canonical bot-side exception. Phase 4 must catch/raise
  `ConversationalApiError` — there is **no** `ApiError(status_code, detail)` type anywhere; any
  Phase-4 handler or test that assumed `ApiError` must be renamed to `ConversationalApiError`.
- `ApiClient` is the single bot→API client, owned here and reused (never re-implemented) by
  Phase 4. Its candidate-action surface is defined in this phase with these **exact** canonical
  names/signatures (Task 3.6 Green block): `get_candidate(candidate_id) -> dict` (returns the
  `{candidate, assignees, messages}` envelope), `approve_candidate(candidate_id) -> dict`,
  `reject_candidate(candidate_id) -> dict`, `patch_candidate(candidate_id, payload) -> dict`,
  `list_assignees(active=True) -> list[dict]`. Phase 4's handlers call exactly these names and its
  `FakeApiClient` mirrors them; if a call site or fake diverges, the call site/fake is wrong, not
  this client.
- `run_once()` snapshot keys `{redis, api, long_poll}` are the bot's readiness contract; Phase 4
  (the sole dispatch owner) builds the real long-poll + callback dispatch + `bot.notify` consumer
  into this `main.py` where `run()` currently logs intent — Phase 6 adds only `ingest.py`.

**Dependency notes (cross-phase):**
- **New runtime deps:** `aiogram>=3.4`, `httpx>=0.27` (declared in `bot/pyproject.toml`). `httpx`
  already appears in `api`'s test extras (`api/pyproject.toml:18`); here it is a first-class bot
  runtime dep.
- **Consumes (must already exist / unchanged):** `POST /api/auth/login`, `GET /api/auth/me`,
  cookie `aiwip_session`, `aiwip_core.health.check_redis`, `aiwip_core.logging.get_logger`,
  `aiwip_core.config` pattern. None of these are modified by this phase.
- **Does NOT depend on Phase 1/2 changes:** this phase touches no API schema, no migration, no
  auth endpoint. It can land independently of Phases 1–2. (Phase 4 will depend on Phase 1's
  `CandidateOut` additive fields and Phase 2's `/api/auth/telegram/redeem` for authz — out of
  scope here.)
- **Producer for later phases:** `aiwip_bot.api_client.ApiClient` and `aiwip_bot.config` are the
  reusable surfaces Phases 4–6 build on.
```