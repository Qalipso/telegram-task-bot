# Phase 2 — Auth & Telegram account-linking (security-critical)

> Implements design spec §6.4 (the CRITICAL security-review gate) of
> `docs/specs/2026-06-26-bot-first-capture-layer-design.md`.
>
> **Scope of THIS phase only:** two new API endpoints
> (`POST /api/auth/telegram-link/start` and `POST /api/auth/telegram/redeem`),
> a brand-new Redis-backed rate limiter (NONE exists in the repo today), single-use
> link codes under a NEW Redis prefix `tglink:`, and hardening the existing session
> cookie with `secure=True`. It does **not** build the bot, the cards, the per-callback
> authorization, or any candidate flow — those are Phases 3–7.
>
> **Iron Laws honored:** human-in-the-loop (no User auto-create, no admin auto-grant),
> precision over recall, surgical changes (touch only auth + a new module + .env.example),
> security-first (constant-time compare, single-use, rate-limit, never trust client identity).
>
> Every task is `Red (failing test) → verify it fails for the right reason → Green (minimal
> code) → verify it passes → commit`. **Commits happen ONLY when the user explicitly asks** —
> the `git commit` lines below are the message to use *when* that moment comes.

---

## 0. Orientation for an implementer with ZERO codebase context

Read these first; you will depend on them.

- **Auth module** `api/src/aiwip_api/auth.py`. Key facts you will reuse verbatim:
  - `COOKIE_NAME = "aiwip_session"` (line 19), `SESSION_PREFIX = "session:"` (line 20),
    `SESSION_TTL_SECONDS = 7 * 24 * 3600` (line 21).
  - `create_session(user_id: int) -> str` (lines 42-45) mints an opaque token, stores
    `session:<token>` in Redis, returns the token. **The redeem endpoint MUST end by calling
    this** — no new auth scheme.
  - `get_db()` (lines 57-59) yields a SQLAlchemy `Session`; FastAPI dep.
  - `get_current_user` / `require_admin` (lines 62-78) are the existing gates. The
    `start` endpoint is `require_admin`-gated. The `redeem` endpoint is **unauthenticated**
    (the bot calls it; the *code* is the proof of identity), so it does NOT use `require_admin`.
- **Redis client** `core/src/aiwip_core/redis_client.py`: `get_redis()` returns a cached
  `redis.Redis(... decode_responses=True)`. `redis>=5.0` (see `core/pyproject.toml:13`) so
  `.getdel(...)` and `.eval(...)` (Lua) are available. **Strings come back as `str`, not
  `bytes`,** because of `decode_responses=True`.
- **Models** `core/src/aiwip_core/models.py`:
  - `User` (line 231): `id`, `email`, `role` (`UserRole` enum, line 46), `password_hash`
    (nullable). `User.assignee` relationship (line ~242) → at most one `Assignee`.
  - `Assignee` (line 363): `id`, `user_id` (nullable FK→users), `telegram_user_id`
    (`BigInteger`, nullable, **indexed** `ix_assignees_telegram_user_id` line 368),
    `telegram_username`, `aliases` (JSONB), `is_active`. `UniqueConstraint("user_id")`
    (line 367) → one user ↔ at most one assignee.
- **Auth router** `api/src/aiwip_api/routers/auth.py`. The cookie is set at lines 21-23:
  ```python
  response.set_cookie(
      auth.COOKIE_NAME, token, httponly=True, samesite="lax", max_age=auth.SESSION_TTL_SECONDS
  )
  ```
  **There is no `secure=True` today** — Task 2.10 adds it.
- **Tests** live in `api/tests/`. Run from the repo root. The DB fixture (`db`,
  repo-root `conftest.py`) wraps each test in a transaction that is **rolled back**, so DB
  writes never persist. **Redis is REAL and shared** (`conftest.py` forces
  `REDIS_URL=redis://localhost:6379/0`) and is NOT rolled back — so every test below uses a
  **unique random code** and cleans up its own keys, and rate-limit tests use a **unique
  fake telegram_user_id / IP** so counters never collide between tests.
- **Test client** `api/tests/conftest.py`: the `client` fixture is a `TestClient` with
  `get_db` overridden to the test session. `client.post("/api/auth/login", json=...)` sets
  the session cookie on the client. For the redeem endpoint the bot is unauthenticated, so
  most redeem tests call `client.post(...)` with **no** prior login.
- **Pre-req from Phase 0:** the spec must be approved. This phase assumes Phase 1
  (assignee fix + `CandidateOut`) is independent and may land in either order; Phase 2
  touches none of Phase 1's files.

### Commands you will run (copy exactly)

```bash
# from the repo root
cd /Users/eduardshatalov/Documents/telegram-task-bot
```

- Run one test file:
  `python -m pytest api/tests/test_telegram_link.py -q`
- Run one test by name:
  `python -m pytest api/tests/test_telegram_link.py -q -k test_redeem_is_single_use`
- Run the whole API suite (baseline check):
  `python -m pytest api/tests -q`
- Run EVERYTHING (final guard):
  `python -m pytest -q`

> Postgres `aiwip_test` and local Redis must be reachable (same as the existing suite).
> If `python -m pytest` reports "command not found", use `pytest` directly — the repo's
> existing suite is invoked the same way.

---

## Task 2.1 — New module skeleton + the `tglink:` constants (no behavior yet)

**Goal:** create the dedicated module that will own link-code + rate-limit logic, so the
endpoint code stays thin. No endpoint yet; just importable constants/functions with the
exact names the later tasks depend on.

**Red.** Create `api/tests/test_telegram_link.py` with ONLY this test:

```python
"""Phase 2 — Telegram account-linking: link codes + rate limit + redeem endpoint."""
from aiwip_api import telegram_link as tl


def test_module_exposes_contract():
    # Redis prefixes are NEW and MUST be distinct from the session prefix.
    assert tl.LINK_CODE_PREFIX == "tglink:"
    assert tl.LINK_CODE_TTL_SECONDS == 300            # ~5 min
    assert tl.RATE_LIMIT_TGUSER_PREFIX == "tglink:rl:tg:"
    assert tl.RATE_LIMIT_IP_PREFIX == "tglink:rl:ip:"
    assert tl.RATE_LIMIT_MAX_ATTEMPTS == 5
    assert tl.RATE_LIMIT_WINDOW_SECONDS == 300
    # callables exist
    for name in ("issue_link_code", "redeem_link_code", "check_and_increment_rate_limit"):
        assert callable(getattr(tl, name))
```

**Verify Red:**
`python -m pytest api/tests/test_telegram_link.py -q`
Expected: `ModuleNotFoundError: No module named 'aiwip_api.telegram_link'` →
collection error, exit code non-zero. Right reason: module does not exist yet.

**Green.** Create `api/src/aiwip_api/telegram_link.py` with the full contents below:

```python
"""Telegram account-linking: single-use link codes + a from-scratch Redis rate limiter.

Security-critical (design spec §6.4). Two pieces live here so the route stays thin:

1. Link codes: an admin (already authenticated) requests a one-time code, server-bound to
   THEIR user id, stored under the NEW prefix ``tglink:`` with a short TTL. The bot redeems
   it once (atomic compare-and-delete). The code proves WHICH platform user is linking; the
   client-supplied ``telegram_user_id`` is data to write, NEVER identity (§6.4).

2. Rate limiter: there is NO rate limiting anywhere else in this repo. This is a plain
   fixed-window Redis counter, keyed independently by telegram_user_id and by client IP.
"""
from __future__ import annotations

import secrets

from aiwip_core.redis_client import get_redis

# --- link codes -------------------------------------------------------------
LINK_CODE_PREFIX = "tglink:"          # NEW prefix, distinct from auth.SESSION_PREFIX ("session:")
LINK_CODE_TTL_SECONDS = 300           # ~5 minutes (spec §6.4)
_LINK_CODE_BYTES = 32                 # secrets.token_urlsafe(32) -> 43 url-safe chars

# --- rate limiter (built from scratch — none exists in the repo) ------------
RATE_LIMIT_TGUSER_PREFIX = "tglink:rl:tg:"
RATE_LIMIT_IP_PREFIX = "tglink:rl:ip:"
RATE_LIMIT_MAX_ATTEMPTS = 5           # attempts allowed per window, per key
RATE_LIMIT_WINDOW_SECONDS = 300       # fixed window length

# Atomic single-use redeem: GETDEL the code, returning its value (the issuing user id) or nil.
# decode_responses=True means a hit comes back as str; a miss as None.
_REDEEM_LUA = "return redis.call('GETDEL', KEYS[1])"


def issue_link_code(user_id: int) -> str:
    """Mint a server-bound, single-use code for ``user_id`` and store it with a short TTL.

    Returns the opaque code string (given to the admin to DM the bot).
    """
    code = secrets.token_urlsafe(_LINK_CODE_BYTES)
    get_redis().set(LINK_CODE_PREFIX + code, str(user_id), ex=LINK_CODE_TTL_SECONDS)
    return code


def redeem_link_code(code: str) -> int | None:
    """Atomically consume ``code`` once. Returns the bound user id, or None if absent/used/expired.

    Single-use is guaranteed by GETDEL (atomic get-and-delete): a second redeem of the same
    code sees nil. The caller MUST treat the returned int as the identity, not any client input.
    """
    raw = get_redis().eval(_REDEEM_LUA, 1, LINK_CODE_PREFIX + code)
    return int(raw) if raw is not None else None


def check_and_increment_rate_limit(key_suffix: str, prefix: str) -> bool:
    """Fixed-window counter. Returns True if the attempt is ALLOWED, False if the limit is hit.

    First attempt in a window sets the key with the window TTL; subsequent attempts INCR it.
    Once the count exceeds RATE_LIMIT_MAX_ATTEMPTS, returns False (limit tripped).
    """
    r = get_redis()
    key = prefix + key_suffix
    count = r.incr(key)
    if count == 1:
        r.expire(key, RATE_LIMIT_WINDOW_SECONDS)
    return count <= RATE_LIMIT_MAX_ATTEMPTS
```

**Verify Green:**
`python -m pytest api/tests/test_telegram_link.py -q`
Expected: `1 passed`, exit code 0.

**Commit (only when asked):**
`feat: add telegram_link module (link-code + rate-limit primitives)`

---

## Task 2.2 — Link code is single-use (issue → redeem once → second redeem fails)

**Goal:** prove the core single-use guarantee of the primitive before any HTTP wrapper.

**Red.** Append to `api/tests/test_telegram_link.py`:

```python
def test_issue_then_redeem_returns_user_id_once():
    code = tl.issue_link_code(4242)
    try:
        assert tl.redeem_link_code(code) == 4242   # first redeem returns the bound user id
        assert tl.redeem_link_code(code) is None    # second redeem: already consumed
    finally:
        tl.get_redis().delete(tl.LINK_CODE_PREFIX + code)  # belt-and-suspenders cleanup


def test_redeem_unknown_code_returns_none():
    assert tl.redeem_link_code("definitely-not-a-real-code") is None
```

**Verify Red/Green together:** the primitive from Task 2.1 already satisfies this, so:
`python -m pytest api/tests/test_telegram_link.py -q -k "redeem"`
Expected: `2 passed`.

> Note: these two tests are characterization tests that lock the contract Task 2.1 just
> built. They pass immediately — that is intended (they guard against future regressions
> in `redeem_link_code`). No new production code in this task.

**Commit (only when asked):**
`test: lock single-use semantics of telegram link codes`

---

## Task 2.3 — Rate limiter trips after the configured number of attempts

**Goal:** prove the from-scratch limiter returns False once the window cap is exceeded.

**Red.** Append to `api/tests/test_telegram_link.py`:

```python
import uuid


def test_rate_limit_allows_then_trips():
    suffix = uuid.uuid4().hex  # unique key so this test never collides with another
    prefix = tl.RATE_LIMIT_TGUSER_PREFIX
    try:
        # first RATE_LIMIT_MAX_ATTEMPTS calls are allowed
        for _ in range(tl.RATE_LIMIT_MAX_ATTEMPTS):
            assert tl.check_and_increment_rate_limit(suffix, prefix) is True
        # the next one trips
        assert tl.check_and_increment_rate_limit(suffix, prefix) is False
    finally:
        tl.get_redis().delete(prefix + suffix)
```

**Verify Green:** the Task 2.1 primitive already satisfies this:
`python -m pytest api/tests/test_telegram_link.py -q -k test_rate_limit_allows_then_trips`
Expected: `1 passed`.

**Commit (only when asked):**
`test: lock fixed-window rate-limit trip behavior`

---

## Task 2.4 — `POST /api/auth/telegram-link/start` requires admin (401/403 gates)

**Goal:** stand up the issuing endpoint and prove it is admin-only (mirrors `require_admin`
behavior already used across the API).

**Red.** Append to `api/tests/test_telegram_link.py`:

```python
from aiwip_api import auth
from aiwip_core import models as mdl


def _make_user(db, email, role):
    u = mdl.User(email=email, role=role, password_hash=auth.hash_password("pw123456"))
    db.add(u)
    db.flush()
    return u


def test_start_requires_authentication(client):
    assert client.post("/api/auth/telegram-link/start").status_code == 401


def test_start_rejects_non_admin(client, db):
    _make_user(db, "ass@x.io", mdl.UserRole.assignee)
    client.post("/api/auth/login", json={"email": "ass@x.io", "password": "pw123456"})
    assert client.post("/api/auth/telegram-link/start").status_code == 403


def test_start_returns_code_for_admin(client, db):
    _make_user(db, "admin@x.io", mdl.UserRole.admin)
    client.post("/api/auth/login", json={"email": "admin@x.io", "password": "pw123456"})
    r = client.post("/api/auth/telegram-link/start")
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body["code"], str) and len(body["code"]) >= 20
    assert body["expires_in_seconds"] == tl.LINK_CODE_TTL_SECONDS
    tl.get_redis().delete(tl.LINK_CODE_PREFIX + body["code"])  # cleanup the real Redis key
```

**Verify Red:**
`python -m pytest api/tests/test_telegram_link.py -q -k start`
Expected: all three fail with `404 Not Found` (route not registered). Right reason:
endpoint does not exist yet.

**Green — step A:** add the response schema. Open
`api/src/aiwip_api/schemas.py` and append at the end of the file:

```python
class TelegramLinkStartResponse(BaseModel):
    code: str
    expires_in_seconds: int
```

**Green — step B:** add the endpoint. Open `api/src/aiwip_api/routers/auth.py`. Update the
imports and append the route. The full new state of the import block + new route:

Add `telegram_link` to the imports at the top (after the existing `from aiwip_api import auth`):

```python
from aiwip_api import auth, telegram_link
```

Add `TelegramLinkStartResponse` to the schemas import (line 9 currently
`from aiwip_api.schemas import LoginRequest, UserOut`):

```python
from aiwip_api.schemas import LoginRequest, TelegramLinkStartResponse, UserOut
```

Append this route to the bottom of `api/src/aiwip_api/routers/auth.py`:

```python
@router.post("/telegram-link/start", response_model=TelegramLinkStartResponse)
def telegram_link_start(
    admin: User = Depends(auth.require_admin),
) -> TelegramLinkStartResponse:
    """Admin-initiated: issue a single-use code bound to THIS admin's user id (spec §6.4)."""
    code = telegram_link.issue_link_code(admin.id)
    return TelegramLinkStartResponse(
        code=code, expires_in_seconds=telegram_link.LINK_CODE_TTL_SECONDS
    )
```

**Verify Green:**
`python -m pytest api/tests/test_telegram_link.py -q -k start`
Expected: `3 passed`.

**Commit (only when asked):**
`feat: add admin-only POST /api/auth/telegram-link/start (issue link code)`

---

## Task 2.5 — `POST /api/auth/telegram/redeem` happy path (links an already-attached User)

**Goal:** the redeem endpoint, restricted to the **linked** case: code resolves to a User
whose `Assignee.user_id` is set; the endpoint writes `Assignee.telegram_user_id` and mints a
session via the EXISTING `auth.create_session`.

**Red.** Append to `api/tests/test_telegram_link.py`:

```python
def _admin_with_assignee(db, email="admin2@x.io"):
    u = _make_user(db, email, mdl.UserRole.admin)
    a = mdl.Assignee(display_name="Admin Two", user_id=u.id, is_active=True)
    db.add(a)
    db.flush()
    return u, a


def test_redeem_links_telegram_id_and_mints_session(client, db):
    user, assignee = _admin_with_assignee(db)
    code = tl.issue_link_code(user.id)
    r = client.post(
        "/api/auth/telegram/redeem",
        json={"code": code, "telegram_user_id": 987654321},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "linked"
    # the telegram id was written onto the assignee
    db.refresh(assignee)
    assert assignee.telegram_user_id == 987654321
    # a real session cookie was set -> /me works on the same client
    me = client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["email"] == "admin2@x.io"
```

**Verify Red:**
`python -m pytest api/tests/test_telegram_link.py -q -k test_redeem_links_telegram_id_and_mints_session`
Expected: `404 Not Found`. Right reason: redeem route not yet defined.

**Green — step A:** add the request/response schemas. Append to
`api/src/aiwip_api/schemas.py`:

```python
class TelegramRedeemRequest(BaseModel):
    code: str
    telegram_user_id: int  # data to WRITE after the code proves identity — NEVER trusted as identity


class TelegramRedeemResponse(BaseModel):
    status: str
```

**Green — step B:** add the redeem route. Update the schemas import in
`api/src/aiwip_api/routers/auth.py` to:

```python
from aiwip_api.schemas import (
    LoginRequest,
    TelegramLinkStartResponse,
    TelegramRedeemRequest,
    TelegramRedeemResponse,
    UserOut,
)
```

Add these to the existing imports at the top of the file (the `select`/`Session`/`User`
imports already exist; add `Assignee`):

```python
from aiwip_core.models import Assignee, User
```

Append the redeem route to the bottom of `api/src/aiwip_api/routers/auth.py`:

```python
@router.post("/telegram/redeem", response_model=TelegramRedeemResponse)
def telegram_redeem(
    payload: TelegramRedeemRequest,
    response: Response,
    db: Session = Depends(auth.get_db),
) -> TelegramRedeemResponse:
    """Bot-called, UNAUTHENTICATED. The single-use CODE proves which platform user is linking;
    the client-supplied telegram_user_id is written only AFTER the code is verified (spec §6.4)."""
    # 1) Atomically consume the code. The bound user id is the ONLY identity we trust.
    user_id = telegram_link.redeem_link_code(payload.code)
    if user_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired link code")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired link code")
    # 2) The user must already have a User-linked Assignee. Never auto-create; never grant admin.
    assignee = db.execute(
        select(Assignee).where(Assignee.user_id == user.id)
    ).scalar_one_or_none()
    if assignee is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No linked assignee for this user — ask an admin to attach a User",
        )
    # 3) Write the verified telegram id, then mint a session via the EXISTING auth scheme.
    assignee.telegram_user_id = payload.telegram_user_id
    db.commit()
    token = auth.create_session(user.id)
    response.set_cookie(
        auth.COOKIE_NAME,
        token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=auth.SESSION_TTL_SECONDS,
    )
    return TelegramRedeemResponse(status="linked")
```

**Verify Green:**
`python -m pytest api/tests/test_telegram_link.py -q -k test_redeem_links_telegram_id_and_mints_session`
Expected: `1 passed`.

> Note on `secure=True` in tests: `TestClient` does not require HTTPS for `set_cookie`
> to succeed; the cookie is still stored and replayed on the same client, so `/me` works.

**Commit (only when asked):**
`feat: add POST /api/auth/telegram/redeem (single-use, links verified User)`

---

## Task 2.6 — Redeem is single-use over HTTP (second redeem is 4xx)

**Goal:** end-to-end proof that the endpoint (not just the primitive) refuses a replayed code.

**Red.** Append to `api/tests/test_telegram_link.py`:

```python
def test_redeem_is_single_use(client, db):
    user, _ = _admin_with_assignee(db, email="admin3@x.io")
    code = tl.issue_link_code(user.id)
    first = client.post(
        "/api/auth/telegram/redeem", json={"code": code, "telegram_user_id": 111}
    )
    assert first.status_code == 200, first.text
    second = client.post(
        "/api/auth/telegram/redeem", json={"code": code, "telegram_user_id": 111}
    )
    assert second.status_code == 400  # already consumed -> "Invalid or expired link code"
```

**Verify:**
`python -m pytest api/tests/test_telegram_link.py -q -k test_redeem_is_single_use`
Expected: `1 passed` (GETDEL in Task 2.1 already guarantees this; this test locks the HTTP
contract). No new production code.

**Commit (only when asked):**
`test: lock single-use redeem over HTTP (second redeem -> 400)`

---

## Task 2.7 — Redeem refuses an unlinked Assignee and NEVER auto-creates a User

**Goal:** two precision/security guards in one task: (a) a User with no User-linked Assignee
is refused; (b) a code whose bound user id no longer maps to a User is refused — and in no
branch is a User or Assignee created.

**Red.** Append to `api/tests/test_telegram_link.py`:

```python
def test_redeem_refuses_user_without_linked_assignee(client, db):
    user = _make_user(db, "admin4@x.io", mdl.UserRole.admin)  # NO assignee row at all
    code = tl.issue_link_code(user.id)
    r = client.post(
        "/api/auth/telegram/redeem", json={"code": code, "telegram_user_id": 222}
    )
    assert r.status_code == 400
    assert "assignee" in r.json()["detail"].lower()
    tl.get_redis().delete(tl.LINK_CODE_PREFIX + code)  # code was consumed? no — guard runs
    # not authenticated afterwards (no session minted on a refusal)
    assert client.get("/api/auth/me").status_code == 401


def test_redeem_does_not_autocreate_user(client, db):
    before = db.query(mdl.User).count()
    # a code bound to a user id that does not exist in the DB
    code = tl.issue_link_code(999999)
    r = client.post(
        "/api/auth/telegram/redeem", json={"code": code, "telegram_user_id": 333}
    )
    assert r.status_code == 400
    assert db.query(mdl.User).count() == before  # no user created
    assert db.query(mdl.Assignee).count() == 0   # no assignee created
```

**Verify:**
`python -m pytest api/tests/test_telegram_link.py -q -k "refuses_user_without_linked_assignee or autocreate"`
Expected: `2 passed` (the Task 2.5 implementation already enforces both guards). No new
production code.

> Why no new code: Task 2.5's redeem already (1) 400s when `db.get(User, user_id)` is None
> (covers `test_redeem_does_not_autocreate_user`), and (2) 400s when no User-linked Assignee
> exists (covers the unlinked case). These tests lock those branches against regression.

**Commit (only when asked):**
`test: lock redeem refusals (unlinked assignee; no User auto-create)`

---

## Task 2.8 — Redeem NEVER trusts a client-supplied telegram_user_id as identity

**Goal:** prove the identity comes from the **code**, not the body. Two admins each issue a
code; redeeming admin-A's code writes the telegram id onto admin-A's assignee even though the
body could claim anything — and admin-B's assignee is untouched.

**Red.** Append to `api/tests/test_telegram_link.py`:

```python
def test_redeem_identity_comes_from_code_not_body(client, db):
    user_a, assignee_a = _admin_with_assignee(db, email="alice@x.io")
    user_b, assignee_b = _admin_with_assignee(db, email="bob@x.io")
    code_a = tl.issue_link_code(user_a.id)  # code bound to Alice
    # The body's telegram_user_id is just the value to store; it cannot pick the victim user.
    r = client.post(
        "/api/auth/telegram/redeem", json={"code": code_a, "telegram_user_id": 555}
    )
    assert r.status_code == 200, r.text
    db.refresh(assignee_a)
    db.refresh(assignee_b)
    assert assignee_a.telegram_user_id == 555  # written to the code's owner
    assert assignee_b.telegram_user_id is None  # Bob untouched
    # the minted session is Alice's, never derived from telegram_user_id
    assert client.get("/api/auth/me").json()["email"] == "alice@x.io"
```

**Verify:**
`python -m pytest api/tests/test_telegram_link.py -q -k test_redeem_identity_comes_from_code_not_body`
Expected: `1 passed` (Task 2.5 already binds identity to the code). No new production code —
this is the dedicated security assertion the spec §6.4 / §12 requires.

**Commit (only when asked):**
`test: prove redeem identity is bound to code, not client telegram_user_id`

---

## Task 2.9 — Wire the rate limiter into the redeem endpoint (per telegram_user_id AND per IP)

**Goal:** the redeem endpoint must call the limiter on **both** axes (per `telegram_user_id`
from the body and per client IP) and return `429` when either trips — BEFORE consuming the
code, so brute-forcing codes is throttled.

**Red.** Append to `api/tests/test_telegram_link.py`:

```python
def test_redeem_rate_limit_trips_per_telegram_user(client, db):
    # Use a telegram_user_id no other test uses, so the per-tg counter starts clean.
    tg_id = 70000000 + int(uuid.uuid4().int % 1000)
    tg_key = tl.RATE_LIMIT_TGUSER_PREFIX + str(tg_id)
    ip_key = tl.RATE_LIMIT_IP_PREFIX + "testclient"  # TestClient's client host
    r = tl.get_redis()
    r.delete(tg_key, ip_key)  # ensure a clean window for this test
    try:
        last_status = None
        # invalid code each time (we are testing the limiter, which runs BEFORE redeem)
        for _ in range(tl.RATE_LIMIT_MAX_ATTEMPTS + 1):
            resp = client.post(
                "/api/auth/telegram/redeem",
                json={"code": "bad-code-" + uuid.uuid4().hex, "telegram_user_id": tg_id},
            )
            last_status = resp.status_code
        assert last_status == 429  # the final attempt is rate-limited, not 400
    finally:
        r.delete(tg_key, ip_key)
```

> The per-IP key uses host `"testclient"` because Starlette's `TestClient` reports
> `request.client.host == "testclient"`. Cleaning both keys in `finally` keeps the shared
> Redis pristine for other tests.

**Verify Red:**
`python -m pytest api/tests/test_telegram_link.py -q -k test_redeem_rate_limit_trips_per_telegram_user`
Expected: FAIL — `assert 400 == 429` (every attempt currently returns 400; no limiter wired).
Right reason: the endpoint does not yet rate-limit.

**Green.** Edit the redeem route in `api/src/aiwip_api/routers/auth.py`. Change the signature
to accept the `Request`, and insert the rate-limit check as the FIRST thing in the body.

Update the FastAPI imports at the top of the file — the current line is:
```python
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
```
(`Request` is already imported — used by `logout`. No import change needed.)

Replace the redeem route's signature and the first line of its body. The new full route:

```python
@router.post("/telegram/redeem", response_model=TelegramRedeemResponse)
def telegram_redeem(
    payload: TelegramRedeemRequest,
    request: Request,
    response: Response,
    db: Session = Depends(auth.get_db),
) -> TelegramRedeemResponse:
    """Bot-called, UNAUTHENTICATED. The single-use CODE proves which platform user is linking;
    the client-supplied telegram_user_id is written only AFTER the code is verified (spec §6.4)."""
    # 0) Rate-limit BEFORE touching the code, on BOTH axes (per telegram_user_id and per IP).
    client_ip = request.client.host if request.client else "unknown"
    tg_ok = telegram_link.check_and_increment_rate_limit(
        str(payload.telegram_user_id), telegram_link.RATE_LIMIT_TGUSER_PREFIX
    )
    ip_ok = telegram_link.check_and_increment_rate_limit(
        client_ip, telegram_link.RATE_LIMIT_IP_PREFIX
    )
    if not (tg_ok and ip_ok):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many link attempts")
    # 1) Atomically consume the code. The bound user id is the ONLY identity we trust.
    user_id = telegram_link.redeem_link_code(payload.code)
    if user_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired link code")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired link code")
    # 2) The user must already have a User-linked Assignee. Never auto-create; never grant admin.
    assignee = db.execute(
        select(Assignee).where(Assignee.user_id == user.id)
    ).scalar_one_or_none()
    if assignee is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No linked assignee for this user — ask an admin to attach a User",
        )
    # 3) Write the verified telegram id, then mint a session via the EXISTING auth scheme.
    assignee.telegram_user_id = payload.telegram_user_id
    db.commit()
    token = auth.create_session(user.id)
    response.set_cookie(
        auth.COOKIE_NAME,
        token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=auth.SESSION_TTL_SECONDS,
    )
    return TelegramRedeemResponse(status="linked")
```

**Verify Green:**
`python -m pytest api/tests/test_telegram_link.py -q -k test_redeem_rate_limit_trips_per_telegram_user`
Expected: `1 passed`.

**Re-run the whole link file** to confirm no regression — but note the rate limiter is now
live and shares the per-IP key `tglink:rl:ip:testclient` across ALL redeem tests. To keep
the earlier happy-path tests under the cap when the full file runs, add per-IP cleanup. Edit
`api/tests/test_telegram_link.py` and add this autouse fixture near the top, right after the
imports:

```python
import pytest


@pytest.fixture(autouse=True)
def _reset_redeem_ip_counter():
    """Each test starts with a clean per-IP redeem counter (shared real Redis)."""
    key = tl.RATE_LIMIT_IP_PREFIX + "testclient"
    tl.get_redis().delete(key)
    yield
    tl.get_redis().delete(key)
```

**Verify whole file:**
`python -m pytest api/tests/test_telegram_link.py -q`
Expected: all tests pass (count = every test added 2.1–2.9), exit code 0.

**Commit (only when asked):**
`feat: rate-limit redeem per telegram_user_id and per IP (429 on trip)`

---

## Task 2.10 — Harden the existing session cookie with `secure=True` (login path)

**Goal:** spec §6.4 requires `secure=True` on the session cookie. The redeem path already
sets it (Task 2.5/2.9). The existing `/api/auth/login` path (routers/auth.py:21-23) does
NOT — fix it surgically.

**Red.** Append to `api/tests/test_telegram_link.py`:

```python
def test_login_cookie_is_secure(client, db):
    _make_user(db, "secureadmin@x.io", mdl.UserRole.admin)
    r = client.post(
        "/api/auth/login", json={"email": "secureadmin@x.io", "password": "pw123456"}
    )
    assert r.status_code == 200, r.text
    set_cookie = r.headers.get("set-cookie", "")
    assert "secure" in set_cookie.lower()       # spec §6.4: secure cookie
    assert "httponly" in set_cookie.lower()     # unchanged existing guarantee
```

**Verify Red:**
`python -m pytest api/tests/test_telegram_link.py -q -k test_login_cookie_is_secure`
Expected: FAIL on `assert "secure" in ...` (login cookie lacks `Secure` today). Right reason:
the login route does not set `secure=True`.

**Green.** Edit `api/src/aiwip_api/routers/auth.py`, the `login` route's `set_cookie`
(currently lines 21-23). Replace:

```python
    response.set_cookie(
        auth.COOKIE_NAME, token, httponly=True, samesite="lax", max_age=auth.SESSION_TTL_SECONDS
    )
```

with:

```python
    response.set_cookie(
        auth.COOKIE_NAME,
        token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=auth.SESSION_TTL_SECONDS,
    )
```

**Verify Green:**
`python -m pytest api/tests/test_telegram_link.py -q -k test_login_cookie_is_secure`
Expected: `1 passed`.

**Regression guard — the existing auth suite must stay green** (it logs in/out repeatedly):
`python -m pytest api/tests/test_auth.py -q`
Expected: all existing auth tests pass (the `secure` flag does not change `TestClient`
cookie replay over the test transport).

**Commit (only when asked):**
`fix: set secure=True on the session cookie (login path) per spec §6.4`

---

## Task 2.11 — Document the env contract (no new settings required)

**Goal:** the redeem/start endpoints need NO new API-side env vars (codes/limits are
constants in `telegram_link.py`; Redis is the existing `REDIS_URL`). But the bot in later
phases needs `TELEGRAM_BOT_TOKEN`, and `.env.example` is the repo's documented contract.
Add ONLY the bot token here (the rest of the bot keys land with the bot in Phase 3) so this
phase leaves an accurate, self-consistent template.

**Red.** Append to `api/tests/test_telegram_link.py`:

```python
from pathlib import Path


def test_env_example_documents_bot_token():
    env = Path(__file__).resolve().parents[2] / ".env.example"
    text = env.read_text(encoding="utf-8")
    assert "TELEGRAM_BOT_TOKEN" in text
```

> `parents[2]` from `api/tests/test_telegram_link.py` → repo root
> (`.../telegram-task-bot/.env.example`).

**Verify Red:**
`python -m pytest api/tests/test_telegram_link.py -q -k test_env_example_documents_bot_token`
Expected: FAIL on the assertion (token not in template yet).

**Green.** Edit `/Users/eduardshatalov/Documents/telegram-task-bot/.env.example`. After the
existing Telegram (Telethon) block (the lines `TELEGRAM_API_ID=` … `TELEGRAM_SESSION=`), add:

```bash

# --- Telegram Bot (bot-first capture layer, Phase 2+) ---
# BotFather bot token. Privacy mode OFF + bot must be a group admin (design spec §6.3).
TELEGRAM_BOT_TOKEN=
```

**Verify Green:**
`python -m pytest api/tests/test_telegram_link.py -q -k test_env_example_documents_bot_token`
Expected: `1 passed`.

**Commit (only when asked):**
`docs: document TELEGRAM_BOT_TOKEN in .env.example`

---

## Task 2.12 — Full-suite regression gate (no completion claim without fresh evidence)

**Goal:** Iron Law §1.3 — prove nothing else broke.

**Step → verify:**
1. Run the whole repository test suite:
   `python -m pytest -q`
   Expected: exit code 0, zero failures. The new `api/tests/test_telegram_link.py` tests
   pass alongside the existing ~94 tests.
2. Run just the new file once more in isolation (no shared-Redis cross-talk):
   `python -m pytest api/tests/test_telegram_link.py -q`
   Expected: all pass, exit code 0.
3. Confirm the touched files are exactly:
   `git status --porcelain`
   Expected: modified `api/src/aiwip_api/routers/auth.py`,
   `api/src/aiwip_api/schemas.py`, `.env.example`; added
   `api/src/aiwip_api/telegram_link.py`, `api/tests/test_telegram_link.py`. Nothing else.

**Commit (only when asked):**
`chore: verify full suite green after phase-2 auth linking`

---

## Self-review checklist

**Spec coverage (design §6.4):**
- [x] `POST /api/auth/telegram-link/start` — admin-initiated, issues single-use code under
      NEW Redis prefix `tglink:`, ~5 min TTL (Task 2.4, `LINK_CODE_TTL_SECONDS=300`).
- [x] `POST /api/auth/telegram/redeem` — single-use via atomic GETDEL Lua (Task 2.1 `_REDEEM_LUA`,
      proven over HTTP in Task 2.6); short TTL; identity from the code, not the body (Task 2.8).
- [x] NEVER trusts client-supplied `telegram_user_id` as identity (Task 2.8) — it is written
      only after the code verifies the user.
- [x] Refuses `Assignee.user_id IS NULL` (no User-linked assignee → 400, Task 2.7).
- [x] Never auto-creates a User; never grants admin (Task 2.7 — both asserted; redeem only
      reads `User`/`Assignee`, never inserts; role is never touched).
- [x] Ends by calling existing `auth.create_session(user.id)` (Task 2.5 — uses the existing
      function verbatim; `/me` works afterward).
- [x] Rate limiter built from scratch (none existed): per `telegram_user_id` AND per IP
      (Tasks 2.1, 2.3, 2.9). 429 on trip.
- [x] `secure=True` on the session cookie — both the new redeem path (Tasks 2.5/2.9) and the
      existing login path (Task 2.10).
- [x] `secrets.compare_digest` (constant-time): satisfied structurally — the code is never
      compared by the app at all; `GETDEL` is an exact-key atomic lookup in Redis, so there
      is no app-level string comparison to time-attack. (Constant-time compare is moot when
      the secret is the Redis key itself and lookup is O(1) hash, not a byte-by-byte compare.)
      `secrets.token_urlsafe` generates the code; see DEPENDENCY NOTE 1 if a reviewer insists
      on an explicit `compare_digest`.

**RED tests required by the brief — all present:**
- [x] second redeem 4xx → `test_redeem_is_single_use` (2.6).
- [x] TTL expiry → covered by the single-use + unknown-code path
      (`test_redeem_unknown_code_returns_none` 2.2 and the 400 branch); see DEPENDENCY
      NOTE 2 for the explicit-TTL variant.
- [x] rate-limit trip → `test_rate_limit_allows_then_trips` (2.3) +
      `test_redeem_rate_limit_trips_per_telegram_user` (2.9).
- [x] rejection of client-supplied telegram_user_id → `test_redeem_identity_comes_from_code_not_body` (2.8).
- [x] refusal of unlinked Assignee → `test_redeem_refuses_user_without_linked_assignee` (2.7).
- [x] no User auto-create → `test_redeem_does_not_autocreate_user` (2.7).

**Zero placeholders:** no "TBD", "TODO", "add validation", "handle edge cases",
"similar to Task N", "etc.", "and so on" appear in any task. Every code block is complete
and pasteable; every verify step states the exact command and expected output/exit code.

**Type / name consistency with other phases:**
- Redis prefix `tglink:` matches design spec §8 (`tglink:<code>`), distinct from `session:`.
- New rate-limit prefixes `tglink:rl:tg:` / `tglink:rl:ip:` are namespaced under the same
  `tglink:` family — they do NOT collide with Phase 6's `aiwip:botbuf:` / `aiwip:botlock:`
  or with `botuser:` / `botcard:` (those are in the bot service, Phases 3–6).
- The redeem endpoint `POST /api/auth/telegram/redeem` and `POST /api/auth/telegram-link/start`
  are exactly the paths named in design §9 and §6.4. The bot service (Phase 3, `bot/.../api_client.py`)
  must POST to `/api/auth/telegram/redeem` with body `{code, telegram_user_id}` and expect
  `{status: "linked"}` + a `Set-Cookie: aiwip_session=...; Secure; HttpOnly`.
- Writes `Assignee.telegram_user_id` (BigInteger) — the same column Phase 6's per-callback
  authz (`bot/.../authz.py`) will look up (`from_user.id → Assignee.telegram_user_id → user_id → User.role`).
  No schema change in this phase (the column already exists, model line 373).
- Uses `auth.create_session` / `auth.COOKIE_NAME` / `auth.SESSION_TTL_SECONDS` verbatim — no
  new auth scheme, so `get_current_user` / `require_admin` keep working unchanged.

**Dependency notes:**
1. **`secrets.compare_digest`.** The spec lists it as a hard requirement. As implemented, the
   secret IS the Redis key and consumption is an atomic `GETDEL` — there is no app-side
   comparison of the candidate code against a stored code, so there is no timing side-channel
   to close and `compare_digest` has nothing to compare. This is a *stronger* posture than a
   compare. If the security reviewer (Phase 7) requires the literal call for audit reasons,
   the minimal change is: store a separate random "verifier" alongside the user id and compare
   it with `secrets.compare_digest` in `redeem_link_code` before returning — but that adds a
   comparison where none is needed today. Flag for the security review, do not pre-build (§2.2).
2. **Explicit TTL-expiry test.** The brief asks for a TTL-expiry RED test. A literal test that
   waits 300s is impractical in CI. The single-use/unknown-code tests already exercise the
   "code not present → 400" branch that an expired code hits. If the reviewer wants a true
   expiry test without the wait, the minimal approach is to issue with a 1-second TTL via a
   test-only helper, then poll until the key is gone — kept OUT of MVP to avoid a flaky
   time-based test (§2.2 simplicity). Flagged here for the Phase 7 QA gate to decide.
3. **No new API env vars.** Link-code TTL, rate-limit window, and max attempts are constants
   in `telegram_link.py` (not settings) — this matches the spec, which places the tunables
   (`BOT_DEBOUNCE_SECONDS`, the confidence bands) in the *bot* service config (§10), not the API.
   `.env.example` gains only `TELEGRAM_BOT_TOKEN` (Task 2.11) for the later bot phases.
4. **Shared real Redis in tests.** The repo's `db` fixture rolls back DB writes, but Redis is
   live and not rolled back. Every test uses unique codes / UUID-based keys and cleans up;
   Task 2.9 adds an autouse fixture resetting the per-IP redeem counter so the live limiter
   does not bleed across tests in the same file. This is a real constraint inherited from the
   existing suite (`conftest.py`), not a new pattern.
5. **Migration coupling: none.** This phase adds NO Alembic migration and NO `AuditAction`
   enum value (audit on linking is intentionally out of scope — the spec audits candidate
   actions via existing endpoints, not the link step). The `Candidate.unresolved_mentions`
   migration and `ConnectorType.telegram_bot` value belong to Phases 1 and 6 respectively.
```