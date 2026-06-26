# Phase 4 — Confirm UX (cards, per-callback authz, approve/reject/edit/assign, digest, quiet-hours)

> Implements design spec §6.1 (bot assignee UX), §6.2 (confirmation policy & anti-fatigue),
> and §6.4 (per-callback authorization), for the new `bot/` service.
> Contract: `docs/specs/2026-06-26-bot-first-capture-layer-design.md`. Do not contradict it.
>
> **Iron Laws in force:** human-in-the-loop (the bot **NEVER** calls `/approve` itself — a human
> taps every approval), precision-over-recall, surgical changes, security-first.

---

## 0. Orientation for an implementer with ZERO codebase context

You are building UX + authorization logic inside an already-scaffolded `bot/` Python service.
Read this whole section before Task 4.1.

### 0.1 What already exists when this phase starts

- **Repo root:** `/Users/eduardshatalov/Documents/telegram-task-bot`
- **Phase 1 already landed.** `api/src/aiwip_api/schemas.py` `CandidateOut` now carries the extra
  fields this phase reads. The post-Phase-1 shape you depend on is:
  ```python
  class CandidateOut(BaseModel):
      model_config = ConfigDict(from_attributes=True)
      id: int
      candidate_type: CandidateType        # enum value e.g. "task"
      title: str | None = None
      summary: str | None = None
      priority: Priority | None = None     # enum value e.g. "high", or None
      due_date: dt.datetime | None = None
      status: CandidateStatus              # "new" | "needs_review" | "edited" | "approved" | "rejected" | ...
      task_confidence: float | None = None
      context_confidence: float | None = None
      assignee_confidence: float | None = None
      priority_confidence: float | None = None
      due_date_confidence: float | None = None
      missing_fields: list[str] | None = None
      assignee_count: int                  # number of linked CandidateAssignee rows (Phase 1 §6.1B)
      assignee_ambiguous: bool             # True when a single mention matched >1 assignee (Phase 1 §6.1B)
      unresolved_mentions: list[str] | None = None  # raw mention text for [Assign…] (Phase 1 §6.1B/C)
      created_at: dt.datetime
  ```
  Over the wire (`GET /api/candidates/{id}`, `GET /api/candidates?status=…`) these serialize as a
  JSON object with those keys; `priority`/`status`/`candidate_type` are plain strings; `due_date`
  is an ISO-8601 string or `null`. **This phase reads that JSON as a `dict` — it does NOT import
  the Pydantic class.**

- **Phase 3 already landed.** The `bot/` service exists and boots. The pieces this phase imports:
  - `bot/src/aiwip_bot/config.py` exposes a `BotSettings` class, an accessor `get_bot_settings()`,
    and a module-level singleton `bot_settings = get_bot_settings()`. **There is no bare `settings`
    symbol and no `Settings` class** — import it as `from aiwip_bot.config import bot_settings as settings`
    (or call `get_bot_settings()`). The fields this phase reads (Phase 3's exact names):
    `quiet_hours_start_utc: int` (UTC hour 0–23), `quiet_hours_end_utc: int` (UTC hour 0–23),
    `quiet_hours_enabled: bool` (default `True`, per §6.2 "quiet-hours default ON";
    env keys `QUIET_HOURS_START_UTC` / `QUIET_HOURS_END_UTC` / `QUIET_HOURS_ENABLED`),
    `bot_digest_interval_seconds: int`, `auto_band: float` (0.90), `review_band: float` (0.60).
    Any wiring that reads quiet-hours off config uses `bot_settings.quiet_hours_start_utc` /
    `bot_settings.quiet_hours_end_utc` — never `settings.quiet_hours_start` (no such attribute).
  - `bot/src/aiwip_bot/api_client.py` exposes a class `ApiClient`. As Phase 3 ships it, the class has
    only `login()`, `me()`, `close()`, and a private `_request()`, and raises
    `ConversationalApiError(message: str, status_code: int | None = None)` (attributes `.message` /
    `.status_code`) on 4xx/5xx — **there is no `ApiError`.** This phase ADDS the candidate-action
    methods below to the real `ApiClient` (Task 4.5b); they are **synchronous**, go through `_request()`,
    return parsed JSON (`dict` / `list`), and raise `ConversationalApiError` on 4xx/5xx:
    - `get_candidate(candidate_id: int) -> dict`            → `GET /api/candidates/{id}` (returns the
      `{"candidate": {...CandidateOut...}, "assignees": [...], "messages": [...]}` envelope)
    - `approve_candidate(candidate_id: int) -> dict`        → `POST /api/candidates/{id}/approve`
    - `reject_candidate(candidate_id: int) -> dict`         → `POST /api/candidates/{id}/reject`
    - `patch_candidate(candidate_id: int, payload: dict) -> dict` → `PATCH /api/candidates/{id}`
    - `list_assignees(active: bool = True) -> list[dict]`   → `GET /api/assignees?active=true`
    - `get_user_by_assignee(...)` is NOT assumed — authz reads the DB directly (Task 4.5).
  - `bot/src/aiwip_bot/state.py` exposes Redis helpers built on `aiwip_core.redis_client.get_redis()`.
    This phase ADDS digest helpers to it (Task 4.9) but does not assume they pre-exist.
  - `bot/pyproject.toml` declares the `aiwip-bot` package (`name = "aiwip-bot"`, `where = ["src"]`)
    and depends on `aiwip-core`. The package is `pip install -e`'d into the repo `.venv`.

- **Test harness.** Root `pytest.ini`, root `conftest.py` (forces `DATABASE_URL`/`REDIS_URL` to
  `localhost` and provides a transactional `db` fixture against Postgres `aiwip_test`).
  Phase 3 added `bot/tests` to `pytest.ini` `testpaths`; if it is missing, Task 4.1 adds it.

### 0.2 Models / enums you will reference (verified, do not re-derive)

From `core/src/aiwip_core/models.py`:
- `Assignee`: `id`, `user_id` (nullable FK→users), `telegram_user_id` (BigInteger, indexed
  `ix_assignees_telegram_user_id`), `telegram_username`, `display_name`, `aliases` (JSONB),
  `is_active` (bool).
- `User`: `id`, `email`, `role` (`UserRole.admin` | `UserRole.assignee`).
- `UserRole.admin == "admin"`.
- `CandidateStatus`: `new`, `needs_review`, `edited`, `approved`, `rejected`, `duplicate`, `error`.

### 0.3 TDD rhythm (Iron Law §1.1 — every task)

Each task is: **Red** (write a failing test) → run it, confirm it fails *for the stated reason* →
**Green** (smallest code that passes) → run it, confirm pass → (only when the user asks) commit.
Run a single test file with:
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest bot/tests/<file>.py -q
```
Run the whole bot suite + full suite at the end of the phase (Task 4.13).

### 0.4 Files this phase creates (all NEW under `bot/src/aiwip_bot/`)

| File | Responsibility | Tasks |
|---|---|---|
| `cards.py` | `CandidateOut` dict → message text + `InlineKeyboardMarkup` | 4.2, 4.3, 4.4 |
| `authz.py` | callback `from_user.id` → `Assignee` → `User` → require admin | 4.5 |
| `handlers.py` | approve / reject / assign / who / settings callback handlers | 4.6, 4.7, 4.8 |
| `digest.py` | coalesce a cycle into ONE digest, quiet-hours, no "Approve all" | 4.9, 4.10, 4.11, 4.12 |
| `bot/tests/test_cards.py`, `test_authz.py`, `test_handlers.py`, `test_digest.py` | RED-first tests | all |

### 0.5 Telegram object shapes used (no live network in tests)

This phase does NOT call Telegram. Handlers and authz take **plain data**, not a live Bot client,
so they are unit-testable. We model the two inbound shapes as lightweight dataclasses the tests
construct directly:

- A **tapper identity**: an `int` Telegram user id (`callback.from_user.id`). Functions take this
  `int` directly — never a live object.
- A **callback payload**: the `callback_data` string. We define the encoding in Task 4.6.

The reply objects the handlers RETURN are plain dataclasses (`CardMessage`, `HandlerResult`) defined
in this phase, so the eventual `main.py` long-poll loop (Phase 3/6) renders them to the Bot API. This
keeps the network edge out of the unit tests.

---

## Task 4.1 — Ensure `bot/tests` is on the test path and the package imports

**Goal:** prove the bot test suite is discoverable and `aiwip_bot` imports, before writing UX code.

### Red

Create `bot/tests/test_phase4_smoke.py`:
```python
"""Phase-4 smoke: the bot package and its Phase-4 modules import."""


def test_aiwip_bot_imports():
    import aiwip_bot  # noqa: F401


def test_phase4_modules_import():
    # These modules are created during Phase 4; this asserts the path is wired.
    import aiwip_bot.cards  # noqa: F401
    import aiwip_bot.authz  # noqa: F401
    import aiwip_bot.handlers  # noqa: F401
    import aiwip_bot.digest  # noqa: F401
```

Run:
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest bot/tests/test_phase4_smoke.py -q
```
**Expected (RED):** collection runs (proves `bot/tests` is on `testpaths`); `test_phase4_modules_import`
**fails** with `ModuleNotFoundError: No module named 'aiwip_bot.cards'`. If instead pytest reports
"no tests ran" / cannot find `bot/tests`, fix `pytest.ini` first (see Green), then re-run.

### Green

If `bot/tests` is **not** already in `pytest.ini` `testpaths`, edit `pytest.ini`:
```ini
[pytest]
testpaths = core/tests api/tests worker/tests bot/tests
python_files = test_*.py
addopts = -ra
filterwarnings =
    ignore:Using `httpx` with `starlette.testclient` is deprecated.*
```
Create the four empty-but-importable modules (they get real content in later tasks):
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && for m in cards authz handlers digest; do printf '"""Phase 4 placeholder — populated by the Confirm-UX tasks."""\n' > "bot/src/aiwip_bot/$m.py"; done
```
Create `bot/tests/__init__.py` if Phase 3 did not (it should exist; create only if missing):
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && test -f bot/tests/__init__.py || : > bot/tests/__init__.py
```
Re-run the command above. **Expected (GREEN):** `2 passed`. Exit code `0`.

**Commit (only if asked):** `chore(bot): wire bot/tests path + phase-4 module stubs`

---

## Task 4.2 — `cards.format_candidate_text`: render a candidate dict to message text

**Goal:** turn a `CandidateOut` JSON dict into the human-readable card body, with field truncation.
Spec §6.1 (show the candidate), §6.2 (status/missing-fields drive what is shown).

### Red

Create `bot/tests/test_cards.py`:
```python
"""Phase 4 — card rendering (text body + keyboard)."""
from aiwip_bot import cards


def _cand(**over):
    base = {
        "id": 7,
        "candidate_type": "task",
        "title": "Ship the Q3 report",
        "summary": "Send the finished report to finance.",
        "priority": "high",
        "due_date": "2026-07-03T00:00:00+00:00",
        "status": "new",
        "task_confidence": 0.95,
        "assignee_confidence": 0.9,
        "priority_confidence": 0.7,
        "due_date_confidence": 0.8,
        "context_confidence": 0.8,
        "missing_fields": [],
        "assignee_count": 1,
        "assignee_ambiguous": False,
        "unresolved_mentions": None,
    }
    base.update(over)
    return base


def test_text_includes_title_and_id():
    text = cards.format_candidate_text(_cand())
    assert "Ship the Q3 report" in text
    assert "#7" in text  # candidate id is visible for traceability


def test_long_title_is_truncated():
    text = cards.format_candidate_text(_cand(title="x" * 400))
    # the title line must be capped (TITLE_MAX_LEN) with an ellipsis
    assert "x" * 400 not in text
    assert "…" in text


def test_missing_fields_render_as_badge():
    text = cards.format_candidate_text(_cand(status="needs_review", missing_fields=["assignee", "due_date"]))
    assert "assignee" in text and "due_date" in text


def test_ambiguous_assignee_shows_unresolved_mention():
    text = cards.format_candidate_text(
        _cand(status="needs_review", assignee_count=0, assignee_ambiguous=True,
              unresolved_mentions=["Саша"])
    )
    assert "Саша" in text
```

Run:
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest bot/tests/test_cards.py -q
```
**Expected (RED):** `AttributeError: module 'aiwip_bot.cards' has no attribute 'format_candidate_text'`.

### Green

Write `bot/src/aiwip_bot/cards.py`:
```python
"""Render a CandidateOut JSON dict to a Telegram card: message text + inline keyboard.

The bot reads candidate JSON (a dict) over the API — it does NOT import the Pydantic schema.
This module is pure (no network), so it is fully unit-testable.

Iron Law: this module renders only. It never decides to approve; it offers buttons a human taps.
"""
from __future__ import annotations

from dataclasses import dataclass

TITLE_MAX_LEN = 120
SUMMARY_MAX_LEN = 280
ELLIPSIS = "…"


def _truncate(value: str | None, limit: int) -> str:
    if not value:
        return ""
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + ELLIPSIS


def _confidence_pct(value: float | None) -> str:
    return f"{round(value * 100)}%" if isinstance(value, (int, float)) else "—"


def format_candidate_text(candidate: dict) -> str:
    """CandidateOut dict -> human-readable card body. Pure string; no side effects."""
    cid = candidate.get("id")
    ctype = candidate.get("candidate_type", "item")
    title = _truncate(candidate.get("title"), TITLE_MAX_LEN) or "(no title)"
    summary = _truncate(candidate.get("summary"), SUMMARY_MAX_LEN)
    priority = candidate.get("priority") or "—"
    due = candidate.get("due_date") or "—"
    status = candidate.get("status", "")
    task_conf = _confidence_pct(candidate.get("task_confidence"))

    lines = [
        f"📥 {ctype.capitalize()} #{cid}",
        f"*{title}*",
    ]
    if summary:
        lines.append(summary)
    lines.append(f"Priority: {priority}   Due: {due}   Confidence: {task_conf}")

    missing = candidate.get("missing_fields") or []
    if missing:
        lines.append("⚠ Missing: " + ", ".join(missing))

    if candidate.get("assignee_ambiguous"):
        mentions = candidate.get("unresolved_mentions") or []
        who = ", ".join(mentions) if mentions else "?"
        lines.append(f"❓ Ambiguous assignee — who is: {who}")
    elif (candidate.get("assignee_count") or 0) == 0:
        mentions = candidate.get("unresolved_mentions") or []
        if mentions:
            lines.append("👤 Unassigned — mentioned: " + ", ".join(mentions))
        else:
            lines.append("👤 Unassigned")

    if status and status != "new":
        lines.append(f"_status: {status}_")
    return "\n".join(lines)
```

Re-run. **Expected (GREEN):** `4 passed`. Exit code `0`.

**Commit (only if asked):** `feat(bot): render candidate card text with truncation + badges`

---

## Task 4.3 — `cards.build_keyboard`: inline keyboard keyed off status & assignee state

**Goal:** §6.2 band→action. `status=new` AND `missing_fields` empty → one-tap Approve/Reject/Assign.
`needs_review` OR missing non-empty → review buttons (no bare one-tap Approve). Ambiguous/unassigned
→ a `Who?`/`Assign…` button. There is **never** an "Approve all" button (§6.2).

### Red

Append to `bot/tests/test_cards.py`:
```python
def _btn_texts(markup):
    return [b.text for row in markup.inline_keyboard for b in row]


def _btn_data(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def test_ready_card_has_approve_reject_assign():
    markup = cards.build_keyboard(_cand(status="new", missing_fields=[], assignee_count=1))
    texts = _btn_texts(markup)
    assert any("Approve" in t for t in texts)
    assert any("Reject" in t for t in texts)
    assert any("Assign" in t for t in texts)


def test_no_approve_all_button_ever():
    markup = cards.build_keyboard(_cand(status="new", missing_fields=[], assignee_count=1))
    texts = _btn_texts(markup)
    assert not any("all" in t.lower() for t in texts)


def test_needs_review_has_no_one_tap_approve():
    markup = cards.build_keyboard(_cand(status="needs_review", missing_fields=["due_date"], assignee_count=1))
    texts = _btn_texts(markup)
    # missing input -> the bot must not offer a bare one-tap Approve
    assert not any(t.strip() in ("Approve", "✅ Approve") for t in texts)
    assert any("Reject" in t for t in texts)


def test_ambiguous_assignee_offers_who():
    markup = cards.build_keyboard(_cand(status="needs_review", assignee_count=0, assignee_ambiguous=True))
    texts = _btn_texts(markup)
    assert any("Who" in t for t in texts)


def test_callback_data_carries_candidate_id():
    markup = cards.build_keyboard(_cand(id=42, status="new", missing_fields=[], assignee_count=1))
    assert all("42" in d for d in _btn_data(markup))
```

Run:
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest bot/tests/test_cards.py -q
```
**Expected (RED):** `AttributeError: module 'aiwip_bot.cards' has no attribute 'build_keyboard'`.

### Green

Add to `bot/src/aiwip_bot/cards.py` (the callback-data encoding is defined here and reused by
`handlers.py` in Task 4.6):
```python
# --- inline keyboard ---------------------------------------------------------

CB_SEP = ":"  # callback_data format:  "<action><CB_SEP><candidate_id>"  (e.g. "approve:42")


@dataclass(frozen=True)
class InlineButton:
    text: str
    callback_data: str


@dataclass(frozen=True)
class InlineKeyboardMarkup:
    inline_keyboard: list[list[InlineButton]]


def encode_callback(action: str, candidate_id: int) -> str:
    return f"{action}{CB_SEP}{candidate_id}"


def _btn(text: str, action: str, candidate_id: int) -> InlineButton:
    return InlineButton(text=text, callback_data=encode_callback(action, candidate_id))


def build_keyboard(candidate: dict) -> InlineKeyboardMarkup:
    """Status/assignee-driven inline keyboard. NEVER includes an 'Approve all' button (§6.2)."""
    cid = int(candidate["id"])
    status = candidate.get("status", "")
    missing = candidate.get("missing_fields") or []
    assignee_count = candidate.get("assignee_count") or 0
    ambiguous = bool(candidate.get("assignee_ambiguous"))

    rows: list[list[InlineButton]] = []

    # A bare one-tap Approve is offered ONLY for a clean, ready candidate (§6.2 low-friction band):
    # status == new AND no missing fields AND exactly one resolved assignee.
    ready = status == "new" and not missing and assignee_count == 1 and not ambiguous
    if ready:
        rows.append([_btn("✅ Approve", "approve", cid)])

    # Assignee disambiguation / assignment row (§6.1 bot UX).
    if ambiguous:
        rows.append([_btn("❓ Who?", "who", cid)])
    elif assignee_count == 0:
        rows.append([_btn("👤 Assign…", "assign", cid)])

    # Reject is always available; it is never destructive of an approved item (server-guarded).
    rows.append([_btn("✏️ Edit", "edit", cid), _btn("🗑 Reject", "reject", cid)])
    return InlineKeyboardMarkup(inline_keyboard=rows)
```

Re-run. **Expected (GREEN):** all `test_cards.py` pass (9 total). Exit code `0`.

**Commit (only if asked):** `feat(bot): build status-driven inline keyboard (no approve-all)`

---

## Task 4.4 — `cards.render_card`: bundle text + keyboard into one `CardMessage`

**Goal:** one entry point the digest/handlers use; returns a render-only dataclass.

### Red

Append to `bot/tests/test_cards.py`:
```python
def test_render_card_bundles_text_and_keyboard():
    card = cards.render_card(_cand(id=5, status="new", missing_fields=[], assignee_count=1))
    assert card.candidate_id == 5
    assert "#5" in card.text
    assert any("Approve" in b.text for row in card.reply_markup.inline_keyboard for b in row)
```

Run:
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest bot/tests/test_cards.py::test_render_card_bundles_text_and_keyboard -q
```
**Expected (RED):** `AttributeError: module 'aiwip_bot.cards' has no attribute 'render_card'`.

### Green

Add to `bot/src/aiwip_bot/cards.py`:
```python
@dataclass(frozen=True)
class CardMessage:
    candidate_id: int
    text: str
    reply_markup: InlineKeyboardMarkup


def render_card(candidate: dict) -> CardMessage:
    return CardMessage(
        candidate_id=int(candidate["id"]),
        text=format_candidate_text(candidate),
        reply_markup=build_keyboard(candidate),
    )
```

Re-run the full file:
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest bot/tests/test_cards.py -q
```
**Expected (GREEN):** `10 passed`. Exit code `0`.

**Commit (only if asked):** `feat(bot): add render_card bundling text + keyboard`

---

## Task 4.5 — `authz.authorize_tapper`: from_user.id → Assignee → User → require admin

**Goal:** §6.4 — the bot authorizes the tapper itself, against the DB, **before** calling any API.
`callback.from_user.id` → `Assignee.telegram_user_id` (indexed) → `Assignee.user_id` → `User` →
require `User.role == admin`. Everyone else (unlinked, non-admin, unknown) is denied. This is the
CRITICAL security gate; uses a real DB session (the root `db` fixture).

### Red

Create `bot/tests/test_authz.py`:
```python
"""Phase 4 — per-callback tapper authorization (§6.4). Real Postgres via the root `db` fixture."""
import pytest

from aiwip_bot import authz
from aiwip_core import models as m


def _admin_user(db):
    u = m.User(email="admin@aiwip.local", role=m.UserRole.admin)
    db.add(u)
    db.flush()
    return u


def _assignee_user(db):
    u = m.User(email="worker@aiwip.local", role=m.UserRole.assignee)
    db.add(u)
    db.flush()
    return u


def test_linked_admin_is_authorized(db):
    admin = _admin_user(db)
    db.add(m.Assignee(display_name="Boss", telegram_user_id=111, user_id=admin.id, is_active=True))
    db.flush()
    result = authz.authorize_tapper(db, telegram_user_id=111)
    assert result.allowed is True
    assert result.user_id == admin.id


def test_unlinked_telegram_user_is_denied(db):
    # an assignee row with NO user_id binding
    db.add(m.Assignee(display_name="Ghost", telegram_user_id=222, user_id=None, is_active=True))
    db.flush()
    result = authz.authorize_tapper(db, telegram_user_id=222)
    assert result.allowed is False


def test_unknown_telegram_user_is_denied(db):
    result = authz.authorize_tapper(db, telegram_user_id=999999)
    assert result.allowed is False
    assert result.user_id is None


def test_linked_non_admin_is_denied(db):
    worker = _assignee_user(db)
    db.add(m.Assignee(display_name="Worker", telegram_user_id=333, user_id=worker.id, is_active=True))
    db.flush()
    result = authz.authorize_tapper(db, telegram_user_id=333)
    assert result.allowed is False
    assert result.user_id == worker.id  # identified, but not permitted


def test_denied_result_has_user_facing_reason(db):
    result = authz.authorize_tapper(db, telegram_user_id=424242)
    assert result.reason  # non-empty "ask an admin"-style message
```

Run:
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest bot/tests/test_authz.py -q
```
**Expected (RED):** `AttributeError: module 'aiwip_bot.authz' has no attribute 'authorize_tapper'`.

### Green

Write `bot/src/aiwip_bot/authz.py`:
```python
"""Per-callback tapper authorization (design spec §6.4 — CRITICAL security gate).

The Telegram tapper's identity (callback.from_user.id) is mapped, AGAINST THE DATABASE, to a
platform User via the Assignee.telegram_user_id link, and admin is required. callback_data is
NEVER trusted to prove identity or permission; only this DB lookup decides.

Denied tappers get a calm "ask an admin" message — the bot never reveals whether the id is known.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from aiwip_core.models import Assignee, User, UserRole

_DENY_MESSAGE = "You are not authorized to do this. Please ask an admin."


@dataclass(frozen=True)
class AuthDecision:
    allowed: bool
    user_id: int | None = None
    reason: str = ""


def authorize_tapper(db: Session, telegram_user_id: int) -> AuthDecision:
    """Map a Telegram user id -> linked admin User. Allow only a linked admin.

    Returns AuthDecision(allowed, user_id, reason). `user_id` is populated even when denied
    (e.g. a linked non-admin) so the caller can audit, but `allowed` gates every action.
    """
    assignee = db.execute(
        select(Assignee).where(Assignee.telegram_user_id == telegram_user_id)
    ).scalars().first()
    if assignee is None or assignee.user_id is None:
        return AuthDecision(allowed=False, user_id=None, reason=_DENY_MESSAGE)

    user = db.get(User, assignee.user_id)
    if user is None:
        return AuthDecision(allowed=False, user_id=None, reason=_DENY_MESSAGE)
    if user.role != UserRole.admin:
        return AuthDecision(allowed=False, user_id=user.id, reason=_DENY_MESSAGE)

    return AuthDecision(allowed=True, user_id=user.id, reason="")
```

Re-run. **Expected (GREEN):** `5 passed`. Exit code `0`.

> Note: this maps the tapper to a User; it does **not** prove the action server-side. That is
> §6.4's second control (re-fetch + still-actionable), enforced in the handlers (Tasks 4.6–4.7).

**Commit (only if asked):** `feat(bot): per-callback tapper authz (linked admin only)`

---

## Task 4.5b — Extend the real `ApiClient` with the five candidate/assignee methods

**Goal:** the handlers (Tasks 4.7–4.8) and the digest emit (Task 4.12) call five `ApiClient`
methods that Phase 3 does **not** ship. Phase 3's `api_client.py` builds `ApiClient` with only
`login()` / `me()` / `close()` / `_request()` and raises `ConversationalApiError(message,
status_code)`. **This task is the canonical owner** of adding the candidate/assignee methods to the
real client, with the EXACT names the `FakeApiClient` mirrors, so production matches the tests.
This resolves the cross-phase contract gap (the methods are Phase-4-owned; Phase 3's
`ConversationalApiError` stays the one error type).

### Red

Create `bot/tests/test_api_client_methods.py`:
```python
"""Phase 4 — the candidate/assignee methods exist on the real ApiClient and route through _request.

We do not hit the network: we stub `_request` and assert each method calls the right verb/path and
returns the parsed JSON. The error type is Phase 3's ConversationalApiError (NOT ApiError)."""
import pytest

from aiwip_bot.api_client import ApiClient, ConversationalApiError


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _client_with_recorder(payload):
    client = ApiClient.__new__(ApiClient)  # bypass __init__/login; we only test the method surface
    calls = []

    def fake_request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return _Resp(payload)

    client._request = fake_request  # type: ignore[attr-defined]
    return client, calls


def test_get_candidate_calls_get_and_returns_json():
    client, calls = _client_with_recorder({"candidate": {"id": 5}, "assignees": [], "messages": []})
    out = client.get_candidate(5)
    assert out == {"candidate": {"id": 5}, "assignees": [], "messages": []}
    assert calls[0][0] == "GET" and calls[0][1] == "/api/candidates/5"


def test_approve_candidate_calls_post():
    client, calls = _client_with_recorder({"id": 1, "source_candidate_id": 5})
    out = client.approve_candidate(5)
    assert out == {"id": 1, "source_candidate_id": 5}
    assert calls[0][0] == "POST" and calls[0][1] == "/api/candidates/5/approve"


def test_reject_candidate_calls_post():
    client, calls = _client_with_recorder({"id": 5, "status": "rejected"})
    client.reject_candidate(5)
    assert calls[0][0] == "POST" and calls[0][1] == "/api/candidates/5/reject"


def test_patch_candidate_sends_payload():
    client, calls = _client_with_recorder({"id": 5, "status": "edited"})
    client.patch_candidate(5, {"assignee_ids": [11]})
    assert calls[0][0] == "PATCH" and calls[0][1] == "/api/candidates/5"
    assert calls[0][2]["json"] == {"assignee_ids": [11]}


def test_list_assignees_calls_get_with_active():
    client, calls = _client_with_recorder([{"id": 10, "display_name": "Alice"}])
    out = client.list_assignees(active=True)
    assert out == [{"id": 10, "display_name": "Alice"}]
    assert calls[0][0] == "GET" and calls[0][1] == "/api/assignees"
    assert calls[0][2]["params"] == {"active": "true"}


def test_conversational_api_error_is_the_error_type():
    # Phase 3's exception is ConversationalApiError(message, status_code) — there is no ApiError.
    err = ConversationalApiError("nope", status_code=404)
    assert err.status_code == 404
    assert "nope" in str(err)
```

Run:
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest bot/tests/test_api_client_methods.py -q
```
**Expected (RED):** `AttributeError: 'ApiClient' object has no attribute 'get_candidate'` (Phase 3
shipped only `login`/`me`/`close`/`_request`).

### Green

Add these methods to the existing `ApiClient` class in `bot/src/aiwip_bot/api_client.py`. Insert
them as instance methods alongside `login()` / `me()`; they reuse the existing `_request()` helper
(which already maps 4xx/5xx to `ConversationalApiError`) and return parsed JSON:
```python
    def get_candidate(self, candidate_id: int) -> dict:
        """GET /api/candidates/{id} → {"candidate": {...}, "assignees": [...], "messages": [...]}."""
        return self._request("GET", f"/api/candidates/{candidate_id}").json()

    def approve_candidate(self, candidate_id: int) -> dict:
        """POST /api/candidates/{id}/approve (human-gated, audited) → promoted WorkItem JSON."""
        return self._request("POST", f"/api/candidates/{candidate_id}/approve").json()

    def reject_candidate(self, candidate_id: int) -> dict:
        """POST /api/candidates/{id}/reject → updated candidate JSON."""
        return self._request("POST", f"/api/candidates/{candidate_id}/reject").json()

    def patch_candidate(self, candidate_id: int, payload: dict) -> dict:
        """PATCH /api/candidates/{id} with the partial-update body → updated candidate JSON."""
        return self._request("PATCH", f"/api/candidates/{candidate_id}", json=payload).json()

    def list_assignees(self, active: bool = True) -> list[dict]:
        """GET /api/assignees?active=true → list of assignee dicts."""
        return self._request(
            "GET", "/api/assignees", params={"active": "true" if active else "false"}
        ).json()
```

> If Phase 3's `_request(method, path, **kwargs)` signature differs (e.g. it takes the body as a
> positional or names it `json_body`), align these five call sites to it — the method NAMES and
> return shapes above are the canonical contract the handlers and `FakeApiClient` depend on; the
> `_request` plumbing is whatever Phase 3 actually built.

Re-run. **Expected (GREEN):** `6 passed`. Exit code `0`.

**Commit (only if asked):** `feat(bot): add candidate/assignee methods to ApiClient (ConversationalApiError)`

---

## Task 4.6 — `handlers` callback parsing + the authz/no-op guard skeleton

**Goal:** define the callback-data parser and the shared guard every handler runs:
(1) authorize the tapper (Task 4.5); (2) re-fetch the candidate by id (untrusted `callback_data`,
§6.4); (3) confirm it is still actionable. Returns a `HandlerResult` (render-only).

### Red

Create `bot/tests/test_handlers.py`:
```python
"""Phase 4 — callback handlers (approve/reject/assign/who). Real DB for authz; fake ApiClient."""
import pytest

from aiwip_bot import handlers
from aiwip_core import models as m


class FakeApiClient:
    """Records calls and returns canned candidate JSON. The bot NEVER calls /approve itself
    except through handle_approve, which a human tap triggers — this fake lets us assert that."""

    def __init__(self, candidate: dict):
        self._candidate = candidate
        self.approved: list[int] = []
        self.rejected: list[int] = []
        self.patched: list[tuple[int, dict]] = []

    def get_candidate(self, candidate_id: int) -> dict:
        return {"candidate": dict(self._candidate, id=candidate_id), "assignees": [], "messages": []}

    def approve_candidate(self, candidate_id: int) -> dict:
        self.approved.append(candidate_id)
        return {"id": 1, "source_candidate_id": candidate_id}

    def reject_candidate(self, candidate_id: int) -> dict:
        self.rejected.append(candidate_id)
        return dict(self._candidate, id=candidate_id, status="rejected")

    def patch_candidate(self, candidate_id: int, payload: dict) -> dict:
        self.patched.append((candidate_id, payload))
        return dict(self._candidate, id=candidate_id, status="edited")

    def list_assignees(self, active: bool = True):
        return [{"id": 10, "display_name": "Alice"}, {"id": 11, "display_name": "Bob"}]


def _admin(db, tg_id=111):
    u = m.User(email=f"admin{tg_id}@aiwip.local", role=m.UserRole.admin)
    db.add(u)
    db.flush()
    db.add(m.Assignee(display_name="A", telegram_user_id=tg_id, user_id=u.id, is_active=True))
    db.flush()
    return u


def test_parse_callback_round_trips():
    from aiwip_bot import cards
    action, cid = handlers.parse_callback(cards.encode_callback("approve", 42))
    assert action == "approve"
    assert cid == 42


def test_parse_callback_rejects_garbage():
    with pytest.raises(ValueError):
        handlers.parse_callback("not-a-valid-payload")
```

Run:
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest bot/tests/test_handlers.py -q
```
**Expected (RED):** `AttributeError: module 'aiwip_bot.handlers' has no attribute 'parse_callback'`.

### Green

Write `bot/src/aiwip_bot/handlers.py`:
```python
"""Callback handlers for the confirm loop (approve / reject / assign / who).

Every handler runs the same security guard (design spec §6.4):
  1. authorize the tapper against the DB (authz.authorize_tapper);
  2. re-fetch the candidate by id (callback_data is UNTRUSTED) and confirm it is still actionable;
  3. only THEN call the existing, admin-gated API endpoint.

Iron Law: the bot NEVER calls /approve on its own. handle_approve runs only because a human tapped
the Approve button, and it still goes through the human-gated POST /api/candidates/{id}/approve.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from aiwip_bot import authz, cards


@dataclass(frozen=True)
class HandlerResult:
    text: str                       # what to show the tapper (toast / message)
    card: cards.CardMessage | None = None   # optional refreshed card to re-render
    did_act: bool = False           # True iff an API mutation actually happened


def parse_callback(data: str) -> tuple[str, int]:
    """Parse "<action>:<candidate_id>" -> (action, candidate_id). Raises ValueError on garbage."""
    if not data or cards.CB_SEP not in data:
        raise ValueError(f"malformed callback_data: {data!r}")
    action, _, rest = data.partition(cards.CB_SEP)
    if not action:
        raise ValueError(f"malformed callback_data: {data!r}")
    return action, int(rest)  # int() raises ValueError on non-numeric id
```

Re-run. **Expected (GREEN):** `2 passed`. Exit code `0`.

**Commit (only if asked):** `feat(bot): callback-data parser + handler result type`

---

## Task 4.7 — `handlers.handle_approve` / `handle_reject` with authz + re-fetch + no-op replay guard

**Goal:** §6.4 — deny unauthorized tappers; re-fetch the candidate; if it is already `approved`
(or `rejected`), the action is a **no-op** (replayed/stale callback must not double-act). Authorized
admin on an actionable candidate → call the existing endpoint.

### Red

Append to `bot/tests/test_handlers.py`:
```python
_READY = {
    "id": 0, "candidate_type": "task", "title": "T", "summary": "S",
    "priority": "high", "due_date": None, "status": "new",
    "task_confidence": 0.95, "missing_fields": [], "assignee_count": 1,
    "assignee_ambiguous": False, "unresolved_mentions": None,
}


def test_approve_denied_for_unlinked_tapper(db):
    api = FakeApiClient(_READY)
    res = handlers.handle_approve(db, api, telegram_user_id=777, candidate_id=5)
    assert res.did_act is False
    assert api.approved == []          # the bot did NOT call /approve
    assert "admin" in res.text.lower()


def test_approve_denied_for_non_admin(db):
    worker = m.User(email="w@aiwip.local", role=m.UserRole.assignee)
    db.add(worker)
    db.flush()
    db.add(m.Assignee(display_name="W", telegram_user_id=555, user_id=worker.id, is_active=True))
    db.flush()
    api = FakeApiClient(_READY)
    res = handlers.handle_approve(db, api, telegram_user_id=555, candidate_id=5)
    assert res.did_act is False
    assert api.approved == []


def test_approve_by_admin_calls_endpoint(db):
    _admin(db, tg_id=111)
    api = FakeApiClient(_READY)
    res = handlers.handle_approve(db, api, telegram_user_id=111, candidate_id=5)
    assert res.did_act is True
    assert api.approved == [5]


def test_replayed_approve_on_already_approved_is_noop(db):
    _admin(db, tg_id=222)
    api = FakeApiClient(dict(_READY, status="approved"))  # server says it's already approved
    res = handlers.handle_approve(db, api, telegram_user_id=222, candidate_id=5)
    assert res.did_act is False
    assert api.approved == []          # re-fetch saw approved -> no second /approve call
    assert "already" in res.text.lower()


def test_reject_by_admin_calls_endpoint(db):
    _admin(db, tg_id=333)
    api = FakeApiClient(_READY)
    res = handlers.handle_reject(db, api, telegram_user_id=333, candidate_id=5)
    assert res.did_act is True
    assert api.rejected == [5]


def test_replayed_reject_on_approved_is_noop(db):
    _admin(db, tg_id=444)
    api = FakeApiClient(dict(_READY, status="approved"))
    res = handlers.handle_reject(db, api, telegram_user_id=444, candidate_id=5)
    assert res.did_act is False
    assert api.rejected == []
```

Run:
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest bot/tests/test_handlers.py -q
```
**Expected (RED):** `AttributeError: module 'aiwip_bot.handlers' has no attribute 'handle_approve'`.

### Green

Add to `bot/src/aiwip_bot/handlers.py`:
```python
# Candidate statuses that are already settled — any approve/reject on them is a no-op (replay guard).
_TERMINAL_STATUSES = {"approved", "rejected"}

_ASK_ADMIN = "You are not authorized to do this. Please ask an admin."


def _guard(db: Session, api, telegram_user_id: int, candidate_id: int):
    """Shared §6.4 guard: (decision, candidate_dict | None).

    On deny, returns (HandlerResult, None). On allow, returns (AuthDecision, candidate_dict)
    where candidate_dict is the freshly re-fetched candidate (callback_data is NOT trusted)."""
    decision = authz.authorize_tapper(db, telegram_user_id)
    if not decision.allowed:
        return HandlerResult(text=decision.reason or _ASK_ADMIN, did_act=False), None
    envelope = api.get_candidate(candidate_id)        # re-fetch by id — never trust the button
    candidate = envelope["candidate"] if "candidate" in envelope else envelope
    return decision, candidate


def handle_approve(db: Session, api, telegram_user_id: int, candidate_id: int) -> HandlerResult:
    guard, candidate = _guard(db, api, telegram_user_id, candidate_id)
    if candidate is None:
        return guard  # denied
    if candidate.get("status") in _TERMINAL_STATUSES:
        return HandlerResult(text="This candidate is already settled — no action taken.", did_act=False)
    api.approve_candidate(candidate_id)               # human-gated endpoint; bot never auto-approves
    return HandlerResult(text=f"Approved #{candidate_id}.", did_act=True)


def handle_reject(db: Session, api, telegram_user_id: int, candidate_id: int) -> HandlerResult:
    guard, candidate = _guard(db, api, telegram_user_id, candidate_id)
    if candidate is None:
        return guard  # denied
    if candidate.get("status") in _TERMINAL_STATUSES:
        return HandlerResult(text="This candidate is already settled — no action taken.", did_act=False)
    api.reject_candidate(candidate_id)
    return HandlerResult(text=f"Rejected #{candidate_id}.", did_act=True)
```

Re-run. **Expected (GREEN):** all 8 `test_handlers.py` tests pass so far. Exit code `0`.

**Commit (only if asked):** `feat(bot): approve/reject handlers with authz + replay no-op guard`

---

## Task 4.8 — `handlers.handle_assign` / `handle_who`: assignee pick → PATCH; edit stub

**Goal:** §6.1 bot UX. `Assign…`/`Who?` list active assignees as choose-buttons; choosing one
patches the candidate (`assignee_ids=[chosen]`). `Edit` (free-text) is a fast-follow per §15 — the
handler returns a "use the web console" message (no force-reply in MVP), but it still authorizes.

### Red

Append to `bot/tests/test_handlers.py`:
```python
def test_assign_lists_active_assignees_as_buttons(db):
    _admin(db, tg_id=611)
    api = FakeApiClient(dict(_READY, assignee_count=0))
    res = handlers.handle_assign(db, api, telegram_user_id=611, candidate_id=5)
    assert res.card is not None
    texts = [b.text for row in res.card.reply_markup.inline_keyboard for b in row]
    assert "Alice" in texts and "Bob" in texts


def test_assign_denied_for_unlinked(db):
    api = FakeApiClient(dict(_READY, assignee_count=0))
    res = handlers.handle_assign(db, api, telegram_user_id=70707, candidate_id=5)
    assert res.card is None
    assert "admin" in res.text.lower()


def test_pick_assignee_patches_candidate(db):
    _admin(db, tg_id=612)
    api = FakeApiClient(dict(_READY, assignee_count=0))
    res = handlers.handle_pick_assignee(db, api, telegram_user_id=612, candidate_id=5, assignee_id=11)
    assert res.did_act is True
    assert api.patched == [(5, {"assignee_ids": [11]})]


def test_pick_assignee_denied_for_non_admin(db):
    worker = m.User(email="w2@aiwip.local", role=m.UserRole.assignee)
    db.add(worker)
    db.flush()
    db.add(m.Assignee(display_name="W2", telegram_user_id=613, user_id=worker.id, is_active=True))
    db.flush()
    api = FakeApiClient(dict(_READY, assignee_count=0))
    res = handlers.handle_pick_assignee(db, api, telegram_user_id=613, candidate_id=5, assignee_id=11)
    assert res.did_act is False
    assert api.patched == []


def test_edit_is_authorized_but_directs_to_console(db):
    _admin(db, tg_id=614)
    api = FakeApiClient(_READY)
    res = handlers.handle_edit(db, api, telegram_user_id=614, candidate_id=5)
    assert res.did_act is False
    assert "console" in res.text.lower() or "web" in res.text.lower()
```

Run:
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest bot/tests/test_handlers.py -q
```
**Expected (RED):** `AttributeError: module 'aiwip_bot.handlers' has no attribute 'handle_assign'`.

### Green

Add to `bot/src/aiwip_bot/handlers.py`:
```python
def _assignee_picker(api, candidate_id: int) -> cards.InlineKeyboardMarkup:
    """One choose-button per active assignee. callback_data: "pick:<candidate_id>:<assignee_id>"."""
    rows: list[list[cards.InlineButton]] = []
    for a in api.list_assignees(active=True):
        label = a.get("display_name") or a.get("telegram_username") or f"#{a['id']}"
        data = f"pick{cards.CB_SEP}{candidate_id}{cards.CB_SEP}{a['id']}"
        rows.append([cards.InlineButton(text=label, callback_data=data)])
    return cards.InlineKeyboardMarkup(inline_keyboard=rows)


def handle_assign(db: Session, api, telegram_user_id: int, candidate_id: int) -> HandlerResult:
    guard, candidate = _guard(db, api, telegram_user_id, candidate_id)
    if candidate is None:
        return guard  # denied
    picker = _assignee_picker(api, candidate_id)
    card = cards.CardMessage(candidate_id=candidate_id, text="Who is responsible?", reply_markup=picker)
    return HandlerResult(text="Pick an assignee.", card=card, did_act=False)


# 'Who?' (ambiguity) and 'Assign…' (zero match) present the same picker.
handle_who = handle_assign


def handle_pick_assignee(
    db: Session, api, telegram_user_id: int, candidate_id: int, assignee_id: int
) -> HandlerResult:
    guard, candidate = _guard(db, api, telegram_user_id, candidate_id)
    if candidate is None:
        return guard  # denied
    if candidate.get("status") in _TERMINAL_STATUSES:
        return HandlerResult(text="This candidate is already settled — no action taken.", did_act=False)
    api.patch_candidate(candidate_id, {"assignee_ids": [assignee_id]})
    return HandlerResult(text=f"Assigned #{candidate_id}.", did_act=True)


def handle_edit(db: Session, api, telegram_user_id: int, candidate_id: int) -> HandlerResult:
    # Free-text title/summary editing is a documented fast-follow (spec §15). For MVP, authorize
    # then direct the admin to the web console for full edits.
    guard, candidate = _guard(db, api, telegram_user_id, candidate_id)
    if candidate is None:
        return guard  # denied
    return HandlerResult(
        text=f"Edit #{candidate_id} fields in the web console for now.", did_act=False
    )


def parse_pick_callback(data: str) -> tuple[int, int]:
    """Parse "pick:<candidate_id>:<assignee_id>" -> (candidate_id, assignee_id)."""
    parts = data.split(cards.CB_SEP)
    if len(parts) != 3 or parts[0] != "pick":
        raise ValueError(f"malformed pick callback_data: {data!r}")
    return int(parts[1]), int(parts[2])
```

Re-run the full file:
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest bot/tests/test_handlers.py -q
```
**Expected (GREEN):** `13 passed`. Exit code `0`.

**Commit (only if asked):** `feat(bot): assign/who/pick/edit handlers (PATCH assignee_ids)`

---

## Task 4.9 — `digest`: per-cycle Redis coalescing of new candidate ids

**Goal:** §6.2 — coalesce **each cycle's** new candidate ids per chat into ONE digest. The dedup/
watermark (Redis `botcard:`) prevents re-surfacing across cycles; this is the *intra-cycle* coalesce
buffer so a burst becomes one message. Stored in Redis under a new key `aiwip:botdigest:{chat}`.

### Red

Create `bot/tests/test_digest.py`:
```python
"""Phase 4 — digest coalescing + quiet-hours + one-message-per-cycle (§6.2)."""
import datetime as dt

import pytest

from aiwip_bot import digest
from aiwip_core.redis_client import get_redis


@pytest.fixture(autouse=True)
def _clean_redis():
    r = get_redis()
    for pattern in ("aiwip:botdigest:*", "botcard:*"):
        for key in r.scan_iter(pattern):
            r.delete(key)
    yield
    for pattern in ("aiwip:botdigest:*", "botcard:*"):
        for key in r.scan_iter(pattern):
            r.delete(key)


def test_stage_then_drain_returns_unique_ids_in_order():
    digest.stage_candidate(chat_id=900, candidate_id=3)
    digest.stage_candidate(chat_id=900, candidate_id=7)
    digest.stage_candidate(chat_id=900, candidate_id=3)  # duplicate within the cycle
    ids = digest.drain_staged(chat_id=900)
    assert ids == [3, 7]


def test_drain_clears_the_buffer():
    digest.stage_candidate(chat_id=901, candidate_id=1)
    assert digest.drain_staged(chat_id=901) == [1]
    assert digest.drain_staged(chat_id=901) == []   # second drain is empty (coalesced once)


def test_buffers_are_per_chat():
    digest.stage_candidate(chat_id=902, candidate_id=1)
    digest.stage_candidate(chat_id=903, candidate_id=2)
    assert digest.drain_staged(chat_id=902) == [1]
    assert digest.drain_staged(chat_id=903) == [2]
```

Run:
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest bot/tests/test_digest.py -q
```
**Expected (RED):** `AttributeError: module 'aiwip_bot.digest' has no attribute 'stage_candidate'`.
(Requires a reachable Redis at `localhost:6379` — the root `conftest.py` sets `REDIS_URL`.)

### Green

Write `bot/src/aiwip_bot/digest.py`:
```python
"""Digest coalescing, quiet-hours, and one-message-per-cycle rendering (design spec §6.2).

MANDATORY in MVP (not a fast-follow): a burst of N new candidates in one cycle is coalesced into a
SINGLE digest message per chat. There is NO "Approve all" — the digest batches the PROMPT only;
each approval remains one human tap → one POST /approve.
"""
from __future__ import annotations

import datetime as dt

from aiwip_core.redis_client import get_redis

# Intra-cycle coalesce buffer (a Redis list of candidate ids awaiting the next digest emit).
DIGEST_KEY = "aiwip:botdigest:{chat}"
_DIGEST_TTL_SECONDS = 24 * 3600  # safety expiry so an orphaned buffer cannot leak forever


def _key(chat_id: int) -> str:
    return DIGEST_KEY.format(chat=chat_id)


def stage_candidate(chat_id: int, candidate_id: int) -> None:
    """Append a new candidate id to this chat's pending-digest buffer (dedup happens at drain)."""
    r = get_redis()
    r.rpush(_key(chat_id), candidate_id)
    r.expire(_key(chat_id), _DIGEST_TTL_SECONDS)


def drain_staged(chat_id: int) -> list[int]:
    """Atomically read-and-clear the buffer; return unique ids in first-seen order."""
    r = get_redis()
    key = _key(chat_id)
    pipe = r.pipeline()
    pipe.lrange(key, 0, -1)
    pipe.delete(key)
    raw, _ = pipe.execute()
    seen: set[int] = set()
    ordered: list[int] = []
    for value in raw:
        cid = int(value)
        if cid not in seen:
            seen.add(cid)
            ordered.append(cid)
    return ordered
```

Re-run. **Expected (GREEN):** `3 passed`. Exit code `0`.

**Commit (only if asked):** `feat(bot): redis-backed per-cycle digest coalesce buffer`

---

## Task 4.9b — `state` cross-cycle watermark (`botcard:`) prevents re-surfacing

**Goal:** §6.2 / §8 — the load-bearing **re-surfacing watermark**: "The Redis watermark prevents
re-surfacing; only debounce prevents burst spam." Spec §8 names the prefix `botcard:` (and `botuser:`
for per-user prefs); Phase 7 §0.2 attributes `botcard:`/`botuser:` to `state.py`. The intra-cycle
buffer (Task 4.9, `aiwip:botdigest:{chat}`) coalesces a single cycle; the watermark is the SEPARATE,
cross-cycle dedup so a candidate staged in two cycles is surfaced **once**. **This task is the
canonical owner** of the `botcard:` watermark.

### Red

Create `bot/tests/test_state_watermark.py`:
```python
"""Phase 4 — cross-cycle surfaced-watermark in state.py (Redis prefix botcard:). Real Redis."""
import pytest

from aiwip_bot import state
from aiwip_core.redis_client import get_redis


@pytest.fixture(autouse=True)
def _clean_redis():
    r = get_redis()
    for key in r.scan_iter("botcard:*"):
        r.delete(key)
    yield
    for key in r.scan_iter("botcard:*"):
        r.delete(key)


def test_unset_watermark_is_zero():
    assert state.get_surfaced_watermark(chat_id=800) == 0


def test_set_then_get_watermark():
    state.set_surfaced_watermark(chat_id=800, candidate_id=12)
    assert state.get_surfaced_watermark(chat_id=800) == 12


def test_watermark_only_advances():
    state.set_surfaced_watermark(chat_id=800, candidate_id=12)
    state.set_surfaced_watermark(chat_id=800, candidate_id=5)   # lower id must not lower the mark
    assert state.get_surfaced_watermark(chat_id=800) == 12


def test_already_surfaced_at_or_below_watermark():
    state.set_surfaced_watermark(chat_id=800, candidate_id=12)
    assert state.already_surfaced(chat_id=800, candidate_id=12) is True   # at the mark
    assert state.already_surfaced(chat_id=800, candidate_id=8) is True    # below the mark
    assert state.already_surfaced(chat_id=800, candidate_id=13) is False  # above → new


def test_watermark_is_per_chat():
    state.set_surfaced_watermark(chat_id=801, candidate_id=20)
    assert state.get_surfaced_watermark(chat_id=802) == 0
```

Run:
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest bot/tests/test_state_watermark.py -q
```
**Expected (RED):** `AttributeError: module 'aiwip_bot.state' has no attribute 'get_surfaced_watermark'`.
(Requires Redis at `localhost:6379` — root `conftest.py` sets `REDIS_URL`.)

### Green

Add to `bot/src/aiwip_bot/state.py` (Phase 3 created this module; append these helpers — keep the
existing `from aiwip_core.redis_client import get_redis` import):
```python
# Cross-cycle re-surfacing watermark (design spec §8 prefix `botcard:`). Stores, per chat, the
# highest candidate id already surfaced to the human, so a later cycle never re-surfaces it.
SURFACED_WATERMARK_KEY = "botcard:{chat}"


def _watermark_key(chat_id: int) -> str:
    return SURFACED_WATERMARK_KEY.format(chat=chat_id)


def get_surfaced_watermark(chat_id: int) -> int:
    """Highest candidate id already surfaced to this chat (0 if never surfaced)."""
    raw = get_redis().get(_watermark_key(chat_id))
    return int(raw) if raw is not None else 0


def set_surfaced_watermark(chat_id: int, candidate_id: int) -> None:
    """Advance the watermark to candidate_id. Monotonic: a lower id never lowers the mark."""
    current = get_surfaced_watermark(chat_id)
    if candidate_id > current:
        get_redis().set(_watermark_key(chat_id), candidate_id)


def already_surfaced(chat_id: int, candidate_id: int) -> bool:
    """True if candidate_id is at-or-below this chat's watermark (i.e. already surfaced)."""
    return candidate_id <= get_surfaced_watermark(chat_id)
```

Re-run. **Expected (GREEN):** `5 passed`. Exit code `0`.

> Wiring note: `digest.emit_cycle` (Task 4.12) consults `state.already_surfaced` to skip ids
> at-or-below the watermark and calls `state.set_surfaced_watermark` after building the digest, so a
> candidate is surfaced once across cycles. `botuser:` (per-user prefs) is the sibling prefix named
> by §8; it is not built in this phase (no consumer here needs it yet).

**Commit (only if asked):** `feat(bot): cross-cycle surfaced-watermark (botcard:) in state.py`

---

## Task 4.10 — `digest.in_quiet_hours`: UTC quiet-hours window (§6.2 / D4)

**Goal:** §6.2 — quiet-hours default ON, UTC. A digest due inside the window holds to the next
window. Support the wrap-around case (e.g. 22:00 → 07:00 spans midnight).

### Red

Append to `bot/tests/test_digest.py`:
```python
def test_quiet_hours_wraparound_window():
    # window 22:00 -> 07:00 UTC
    assert digest.in_quiet_hours(dt.time(23, 0), start=22, end=7) is True
    assert digest.in_quiet_hours(dt.time(3, 0), start=22, end=7) is True
    assert digest.in_quiet_hours(dt.time(12, 0), start=22, end=7) is False


def test_quiet_hours_same_day_window():
    # window 01:00 -> 06:00 UTC
    assert digest.in_quiet_hours(dt.time(3, 0), start=1, end=6) is True
    assert digest.in_quiet_hours(dt.time(8, 0), start=1, end=6) is False


def test_quiet_hours_disabled_is_never_quiet():
    assert digest.in_quiet_hours(dt.time(3, 0), start=22, end=7, enabled=False) is False
```

Run:
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest bot/tests/test_digest.py -k quiet_hours -q
```
**Expected (RED):** `AttributeError: module 'aiwip_bot.digest' has no attribute 'in_quiet_hours'`.

### Green

Add to `bot/src/aiwip_bot/digest.py`:
```python
def in_quiet_hours(now_utc: dt.time, start: int, end: int, enabled: bool = True) -> bool:
    """True if `now_utc` (a UTC time-of-day) falls in the quiet window [start:00, end:00).

    start/end are UTC hours (0-23). Handles the wrap-around case where start > end (spans midnight).
    When enabled is False, it is never quiet. Quiet-hours default ON (§6.2)."""
    if not enabled:
        return False
    hour = now_utc.hour
    if start == end:
        return False  # zero-width window
    if start < end:
        return start <= hour < end
    # wrap-around (e.g. 22 -> 7): quiet if at/after start OR before end
    return hour >= start or hour < end
```

Re-run. **Expected (GREEN):** `3 passed`. Exit code `0`.

**Commit (only if asked):** `feat(bot): UTC quiet-hours window with wrap-around`

---

## Task 4.11 — `digest.build_digest`: ONE message; counts ready vs need-input; no "Approve all"

**Goal:** §6.2 — given the cycle's candidate dicts, build ONE digest text:
`N new: M ready · K need input`, with per-candidate one-tap rows that route to the *normal*
single-item handlers. Assert there is **no** "Approve all" anywhere.

### Red

Append to `bot/tests/test_digest.py`:
```python
def _ready(cid):
    return {"id": cid, "candidate_type": "task", "title": f"Task {cid}", "status": "new",
            "missing_fields": [], "assignee_count": 1, "assignee_ambiguous": False,
            "unresolved_mentions": None}


def _needs(cid):
    return {"id": cid, "candidate_type": "task", "title": f"Task {cid}", "status": "needs_review",
            "missing_fields": ["assignee"], "assignee_count": 0, "assignee_ambiguous": False,
            "unresolved_mentions": ["Саша"]}


def test_digest_counts_ready_and_need_input():
    d = digest.build_digest([_ready(1), _ready(2), _needs(3)])
    assert "3 new" in d.text
    assert "2 ready" in d.text
    assert "1 need" in d.text


def test_digest_has_no_approve_all_button():
    d = digest.build_digest([_ready(1), _ready(2)])
    texts = [b.text for row in d.reply_markup.inline_keyboard for b in row]
    assert not any("all" in t.lower() for t in texts)


def test_digest_one_row_per_candidate_routes_to_single_item():
    d = digest.build_digest([_ready(1), _needs(3)])
    datas = [b.callback_data for row in d.reply_markup.inline_keyboard for b in row]
    # each button targets a single candidate id (single-item human judgement preserved)
    assert any(data.endswith("1") for data in datas)
    assert any(data.endswith("3") for data in datas)


def test_empty_digest_is_none():
    assert digest.build_digest([]) is None
```

Run:
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest bot/tests/test_digest.py -k digest -q
```
**Expected (RED):** `AttributeError: module 'aiwip_bot.digest' has no attribute 'build_digest'`.

### Green

Add to `bot/src/aiwip_bot/digest.py` (imports `cards` for the button types/encoding — keep the
import at the top of the file with the others):
```python
from aiwip_bot import cards  # add to the existing import block at the top of digest.py


def _is_ready(candidate: dict) -> bool:
    return (
        candidate.get("status") == "new"
        and not (candidate.get("missing_fields") or [])
        and (candidate.get("assignee_count") or 0) == 1
        and not candidate.get("assignee_ambiguous")
    )


def build_digest(candidates: list[dict]) -> cards.CardMessage | None:
    """Coalesce a cycle's candidates into ONE digest message. Returns None for an empty cycle.

    No 'Approve all': each row targets ONE candidate so every approval stays a single human tap."""
    if not candidates:
        return None
    ready = [c for c in candidates if _is_ready(c)]
    need = [c for c in candidates if not _is_ready(c)]
    text = (
        f"📋 {len(candidates)} new: {len(ready)} ready · {len(need)} need input\n"
        "Tap a candidate to review it."
    )
    rows: list[list[cards.InlineButton]] = []
    for c in candidates:
        cid = int(c["id"])
        title = (c.get("title") or f"#{cid}")[:40]
        # "open" routes to the per-item card (single-item judgement; NOT a batch approve).
        rows.append([cards.InlineButton(text=f"{title}", callback_data=cards.encode_callback("open", cid))])
    return cards.CardMessage(candidate_id=0, text=text, reply_markup=cards.InlineKeyboardMarkup(inline_keyboard=rows))
```

Re-run. **Expected (GREEN):** the 4 digest-build tests pass. Exit code `0`.

**Commit (only if asked):** `feat(bot): coalesced one-message digest (counts, per-item rows, no approve-all)`

---

## Task 4.12 — Integration: burst of N candidates → exactly ONE digest message

**Goal:** the spec's headline confirmation test (§12, §6.2): a burst of N staged candidates yields
**exactly one** digest, not N cards. Wires stage → drain → build into one assertion.

### Red

Append to `bot/tests/test_digest.py`:
```python
class _FakeApiForDigest:
    def __init__(self, by_id):
        self._by_id = by_id

    def get_candidate(self, candidate_id: int) -> dict:
        return {"candidate": self._by_id[candidate_id], "assignees": [], "messages": []}


def test_burst_of_n_candidates_produces_exactly_one_digest():
    chat_id = 950
    cands = {i: _ready(i) for i in range(1, 6)}  # 5 candidates in one burst
    for cid in cands:
        digest.stage_candidate(chat_id=chat_id, candidate_id=cid)

    api = _FakeApiForDigest(cands)
    messages = digest.emit_cycle(chat_id=chat_id, api=api)

    assert len(messages) == 1                       # exactly ONE digest, not 5 cards
    assert "5 new" in messages[0].text
    # the buffer is drained -> a second emit in the same cycle yields nothing
    assert digest.emit_cycle(chat_id=chat_id, api=api) == []
```

Run:
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest bot/tests/test_digest.py -k burst -q
```
**Expected (RED):** `AttributeError: module 'aiwip_bot.digest' has no attribute 'emit_cycle'`.

### Green

Add to `bot/src/aiwip_bot/digest.py`:
```python
from aiwip_bot import state  # add to the existing import block at the top of digest.py


def emit_cycle(chat_id: int, api) -> list[cards.CardMessage]:
    """Drain this chat's staged ids, skip any at-or-below the cross-cycle watermark, fetch the rest,
    and return AT MOST ONE digest message.

    Returns [] when nothing new is staged. Two anti-spam controls cooperate: the `botcard:` watermark
    (state.already_surfaced) prevents cross-cycle re-surfacing; the single-message guarantee here
    prevents intra-cycle fan-out. After building the digest the watermark advances to the highest id
    surfaced, so the same candidate is never surfaced twice."""
    ids = [cid for cid in drain_staged(chat_id) if not state.already_surfaced(chat_id, cid)]
    if not ids:
        return []
    candidates: list[dict] = []
    for cid in ids:
        envelope = api.get_candidate(cid)
        candidates.append(envelope["candidate"] if "candidate" in envelope else envelope)
    message = build_digest(candidates)
    if message is None:
        return []
    state.set_surfaced_watermark(chat_id, max(ids))  # advance the watermark past what we surfaced
    return [message]
```

Re-run. **Expected (GREEN):** `1 passed`. Exit code `0`.

Then run the whole digest file:
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest bot/tests/test_digest.py -q
```
**Expected:** `11 passed`. Exit code `0`.

**Commit (only if asked):** `feat(bot): emit_cycle — exactly one digest per burst`

---

## Task 4.13 — Phase verification: full bot suite + whole-repo baseline green

**Goal:** Iron Law §3.5 — fresh evidence the phase is complete and broke nothing.

### Verify

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest bot/tests -q
```
**Expected:** all Phase-4 tests pass (`test_phase4_smoke` 2, `test_cards` 10, `test_authz` 5,
`test_handlers` 13, `test_digest` 11 = **41 passed**). Exit code `0`.

Then the whole repo (proves no regression in the existing ~94-test baseline):
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest -q
```
**Expected:** the prior baseline count **plus** the 41 new bot tests, all passing, exit code `0`.
Read the summary line; confirm `0 failed`. (Container checks have the stale-image gotcha — run
against on-disk source as above, not inside a possibly-stale image.)

**Commit (only if asked):** `test(bot): phase-4 confirm-UX suite green; baseline intact`

---

## Self-review checklist

**Spec coverage (design §6.1 / §6.2 / §6.4):**
- [x] §6.1 bot UX: `len==1` shown (card text + ready keyboard); `len>1` → `[Who?]` (Task 4.3/4.8);
      `len==0` → `[Assign…]` from `GET /api/assignees?active=true` (Task 4.8); unresolved mention
      string surfaced in the card (Task 4.2).
- [x] §6.1(D) stale button safety: `handle_pick_assignee` PATCHes `assignee_ids=[chosen]`; the API
      (Phase 1) validates inactive/non-existent ids (422) — the bot relies on that server gate and
      re-fetches before acting (Task 4.7/4.8).
- [x] §6.2 bands→action: ready (`new` + empty missing + 1 assignee) → one-tap Approve; otherwise no
      bare Approve (Task 4.3); `<0.60` never surfaced (the bot only renders candidates handed to it;
      it never resurrects dropped ones — no code path constructs a card from a sub-0.60 item).
- [x] §6.2 debounce/coalesce MANDATORY: one digest per cycle (Tasks 4.9, 4.12); per-chat buffers.
- [x] §6.2 quiet-hours default ON, UTC, wrap-around (Task 4.10).
- [x] §6.2 NO "Approve all": asserted in keyboard (4.3), digest keyboard (4.11), and integration
      (no batch-approve callback anywhere).
- [x] §6.4 per-callback authz: `from_user.id` → `Assignee.telegram_user_id` → `Assignee.user_id` →
      `User` → require `role==admin` (Task 4.5); denied for unlinked / unknown / non-admin.
- [x] §6.4 callback_data untrusted: every handler re-fetches the candidate by id and confirms it is
      still actionable before acting (Task 4.7/4.8 `_guard`).
- [x] Iron Law human-in-the-loop: the bot NEVER calls `/approve` itself — `handle_approve` runs only
      on a human tap and still POSTs to the human-gated endpoint; asserted by `api.approved == []`
      on every denied/replayed path (Task 4.7).
- [x] RED tests required by the brief all present: non-admin/unlinked tapper denied
      (`test_authz`, `test_approve_denied_*`); replayed callback on already-approved → no-op
      (`test_replayed_approve_on_already_approved_is_noop`, `..._reject_on_approved...`); burst of N
      → exactly one digest (`test_burst_of_n_candidates_produces_exactly_one_digest`).

**Zero placeholders:** no "TBD"/"TODO"/"add validation"/"handle edge cases"/"similar to Task N"/
"etc."/"and so on" anywhere; every code block is complete and runnable.

**Type / name consistency with other phases:**
- Consumes Phase 1 `CandidateOut` fields by exact name: `assignee_count`, `assignee_ambiguous`,
  `unresolved_mentions`, `assignee_confidence`, `priority_confidence`, `due_date_confidence`,
  `context_confidence`. If Phase 1 names these differently, the card/digest readers must be updated
  in lockstep (this is the only cross-phase data contract this phase reads).
- Consumes Phase 3 `bot/src/aiwip_bot/config.py` `settings` (quiet-hours fields, bands) and
  `api_client.py` `ApiClient` method names: `get_candidate`, `approve_candidate`,
  `reject_candidate`, `patch_candidate`, `list_assignees`. The tests use a `FakeApiClient` with
  those exact method names, so the real `ApiClient` must match them (or Phase 3 must expose them).
- Consumes existing API verbatim (no new endpoints introduced here): `POST /api/candidates/{id}/approve`,
  `POST /api/candidates/{id}/reject`, `PATCH /api/candidates/{id}` (`assignee_ids`),
  `GET /api/assignees?active=true`, `GET /api/candidates/{id}`.
- Models referenced by exact name: `Assignee.telegram_user_id`, `Assignee.user_id`,
  `Assignee.is_active`, `User.role`, `UserRole.admin`, `CandidateStatus` values `approved`/`rejected`.

**Dependency notes:**
- **Phase 1 must land first** (CandidateOut fields) — `cards`/`digest` read them. If absent, card
  rendering still runs (uses `.get()` with defaults) but ambiguity/assignee badges go dark.
- **Phase 3 must land first** (the `bot/` package, `config.py settings`, `api_client.ApiClient`).
  Task 4.1 only stubs the four Phase-4 modules; it assumes `aiwip_bot` already imports.
- **Redis at `localhost:6379`** is required for `test_digest.py` (root `conftest.py` sets `REDIS_URL`).
  **Postgres `aiwip_test`** is required for `test_authz.py` / `test_handlers.py` (root `db` fixture).
- This phase introduces NO migrations, NO endpoints, NO config keys. It introduces Redis key
  `aiwip:botdigest:{chat}` (intra-cycle coalesce buffer) — distinct from the watermark `botcard:`
  and the buffer `aiwip:botbuf:{chat}` (Phase 6). New files: `bot/src/aiwip_bot/{cards,authz,handlers,digest}.py`
  and the four `bot/tests/test_*.py`.
- The `open` callback action (digest row → per-item card) and `edit` (directs to web console) are
  handled by the long-poll dispatcher in `main.py` (Phase 3/6 owns dispatch wiring); this phase
  defines the encoding and the per-item handlers they route to.
