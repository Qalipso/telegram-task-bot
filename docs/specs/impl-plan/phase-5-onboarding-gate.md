# Phase 5 — Onboarding gate (configure-before-capture)

> Implements design spec §7 (onboarding flow) and the owner's onboarding rule in §2.
> Contract of record: `docs/specs/2026-06-26-bot-first-capture-layer-design.md`.
> This phase delivers the **configure-before-capture gate**: when the bot is added to a group it
> first asks for a destination/board, saves per-chat config in Redis, marks the chat configured,
> and only **then** does an inbound message reach the extract buffer. An **unconfigured** chat
> captures **nothing** (no `aiwip:botbuf:{chat}` push, no `aiwip:jobs` enqueue).
>
> **Gate-ownership split with Phase 6 (canonical).** This phase owns the **gate predicate**
> `state.is_chat_configured(chat_id)` and the **onboarding** module — nothing else in the capture
> path. It does **not** define a second buffer writer: there is exactly **one**
> `bot/src/aiwip_bot/ingest.py`, whose production capture entrypoint
> `ingest_message(external_chat_id, record, *, debounce_seconds, is_configured=...)` (plus
> `record_from_update`) is authored by **Phase 6**, which owns debounce and the buffer push via
> `aiwip_core.queue.push_botbuf`. Phase 5 wires the gate **into** that single ingest by requiring
> Phase 6's `is_configured` default to delegate to `state.is_chat_configured`. Phase 5 must **not**
> introduce `ingest.buffer_key`, `ingest.handle_inbound_message`, a local `RPUSH`, or push the raw
> `{chat_id, message_id, …}` dict — the canonical buffer record is Phase 6's
> FetchedMessage-mirroring shape (see Task 5.3).

---

## 0. Orientation for an implementer with zero codebase context

You are working in the monorepo `telegram-task-bot`. It has independent Python packages:

- `core/` — shared library `aiwip_core` (config, models, redis client, queue). Installed as `aiwip-core`.
- `worker/` — `aiwip_worker` (sync/extract pipeline). Mirrors the layout you will reuse for the bot.
- `api/` — FastAPI app.
- `bot/` — the **new** bot service package `aiwip_bot`, scaffolded in **Phase 3** and extended in **Phase 4**.

### 0.1 Redis is the only external dependency for this phase

Every task in this phase exercises **Redis only** — no Postgres, no OpenAI, no live Telegram.
Tests in `bot/tests/` use a real **local** Redis (the same pattern as `worker/tests/test_queue.py`,
which calls `get_redis()` directly against `redis://localhost:6379/0`). Confirm Redis is up before
you start:

```bash
redis-cli -h localhost -p 6379 ping
```

Expected output:

```
PONG
```

If you do not get `PONG`, start Redis (`docker compose up -d redis`, or a local `redis-server`)
before running any test in this phase. The root `conftest.py` forces `REDIS_URL` to
`redis://localhost:6379/0`, so `aiwip_core.redis_client.get_redis()` resolves to local Redis during tests.

### 0.2 Surface this phase consumes from earlier phases (contracts you must NOT contradict)

These were established in **Phase 3** (scaffold) and **Phase 4** (confirm UX). This phase **depends on
exactly these names**; if a name differs in the real Phase-3/4 code, reconcile to the Phase-3/4 name and
note the deviation — do not silently fork. The relevant pieces:

| Symbol | Module | Role | Defined by |
|---|---|---|---|
| `get_redis()` | `aiwip_core.redis_client` | Redis client factory, `decode_responses=True` | exists today (`core/src/aiwip_core/redis_client.py:12`) |
| `enqueue_sync(chat_id, trigger=..., user_id=..., attempts=...)` | `aiwip_core.queue` | LPUSH a `telegram.sync` job onto `aiwip:jobs` | exists today (`core/src/aiwip_core/queue.py:36`) |
| `JOBS_KEY = "aiwip:jobs"` | `aiwip_core.queue` | the job-list key | exists today (`core/src/aiwip_core/queue.py:15`) |
| `bot/src/aiwip_bot/state.py` | `aiwip_bot.state` | Redis state helpers (watermark, prefs, link codes, **buffer**, **locks**, **per-chat config**) | Phase 3 (spec §10) — **this phase ADDS the per-chat-config helpers** |
| `bot/src/aiwip_bot/ingest.py` | `aiwip_bot.ingest` | inbound msg → **configure-gate check** → buffer push → debounced enqueue. The capture entrypoint `ingest_message(...)` + `record_from_update(...)` and the buffer push (`queue.push_botbuf`) are authored by **Phase 6**. | Phase 3 skeleton / **Phase 6 owns the capture body**; **this phase ONLY supplies the gate predicate** `state.is_chat_configured` that Phase 6's `is_configured` default calls — it does not author a second buffer writer |
| `bot/src/aiwip_bot/onboarding.py` | `aiwip_bot.onboarding` | configure-before-capture flow + per-chat config UX | **this phase creates it** |

> **Standalone-authoring note.** This phase is written so it can be implemented even if Phases 3–4
> are not yet merged on your branch: the task that touches `state.py` shows the **complete** file
> content as it must exist after this phase, and §0.3 below makes the `bot/` package importable. If
> Phase 3 already created `state.py`, you are *adding the marked blocks* to the existing file (the
> task notes which functions are new); the rest of that file stays exactly as Phase 3 left it. Do
> not delete Phase-3/4 code.
>
> **`ingest.py` is NOT authored here.** The production capture path in `ingest.py`
> (`record_from_update`, `ingest_message`, the buffer push, and the `is_configured` default) is
> authored by **Phase 6**. This phase only verifies the gate predicate it exposes
> (`state.is_chat_configured`) behaves correctly, and pins the contract that Phase 6's
> `_default_is_configured` must call `state.is_chat_configured` (Task 5.3). Phase 5 does not create
> or recreate `ingest.py`.

### 0.3 Redis key contracts owned by the bot (spec §8)

This phase reads/writes these Redis keys (all values are JSON unless noted):

| Key pattern | Owner phase | Meaning |
|---|---|---|
| `aiwip:botbuf:{chat}` | **Phase 6** (sole writer, via `queue.push_botbuf`; this phase does NOT push to it) | per-chat inbound message buffer (Redis list) |
| `aiwip:botlock:{chat}` | Phase 6 | per-chat debounce lock |
| `aiwip:botcfg:{chat}` | **this phase** | per-chat config JSON (`destination`, `surface_mode`, `debounce_seconds`, `quiet_hours`, `configured` flag) |
| `aiwip:jobs` | core | the worker job list (`JOBS_KEY`) |

> **Buffer record shape (canonical, owned by Phase 6).** The records written to `aiwip:botbuf:{chat}`
> mirror Phase 6's `FetchedMessage` and are written **only** by `queue.push_botbuf` after
> `ingest.record_from_update` maps a Telegram update. Keys: `external_message_id: int`,
> `sender_external_id: int|None`, `sender_username: str|None`, `sender_display_name: str|None`,
> `text: str|None`, `sent_at: ISO-8601 str`, `raw: dict`, `message_type: str = "text"`,
> `attachments: list`. Phase 5 never writes this buffer and never pushes the raw
> `{chat_id, message_id, from_user_id, text, date}` inbound dict — a Phase-5-shaped record would
> raise `KeyError('external_message_id')` when Phase 6's `BotApiConnector` drains it.

`{chat}` is the Telegram chat id (an integer, formatted as a decimal string in the key).

### 0.4 Test command for this phase

Run the bot suite from the **repo root** (`pytest.ini` lives there):

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest bot/tests -q
```

`pytest.ini` `testpaths` must include `bot/tests` (added in Task 5.0). Until then, target the file
path directly as shown in each task.

---

## Task 5.0 — Make `bot/tests` discoverable and the `aiwip_bot` package importable

**Goal:** guarantee the bot package and its test dir are wired into the repo's pytest setup so every
later RED test in this phase actually runs. This is plumbing, not product code, so there is no RED
test for it; the *verify* step is that a trivial bot test collects and passes.

### Step 1 — ensure the bot package skeleton exists

If `bot/src/aiwip_bot/__init__.py` does **not** exist (Phase 3 not yet merged on your branch),
create the package directory and these two files. If Phase 3 already created them, **skip this step**
(do not overwrite Phase-3 content).

Create `bot/src/aiwip_bot/__init__.py`:

```python
"""aiwip_bot — Telegram Bot API service (capture, confirm, onboarding)."""
```

Create `bot/pyproject.toml` (mirrors `worker/pyproject.toml`). This MUST be byte-for-byte the
**Phase 3** canonical `pyproject.toml` — name `aiwip-bot`, version `0.1.0`, dependencies
`["aiwip-core", "aiogram>=3.4", "httpx>=0.27"]` (aiogram is the bot's Telegram library, needed by
the Phase 3/4 main loop; do NOT omit it). If Phase 3 has already authored this file, **skip this
step** and do not overwrite it — Phase 3 owns `pyproject.toml`.

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "aiwip-bot"
version = "0.1.0"
description = "Telegram Bot API service (capture, confirm, onboarding) for the AI Work Intelligence Platform."
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

### Step 2 — install the bot package editable into the active venv (so imports resolve)

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pip install -e ./bot
```

Expected output ends with a line containing:

```
Successfully installed aiwip-bot-0.1.0
```

(If it is already installed editable, pip prints `Requirement already satisfied` / re-uses it — that is fine.)

### Step 3 — add `bot/tests` to pytest `testpaths`

Read `pytest.ini` first. It currently reads:

```
testpaths = core/tests api/tests worker/tests
```

Change that one line to:

```
testpaths = core/tests api/tests worker/tests bot/tests
```

(Leave every other line in `pytest.ini` unchanged.) If Phase 3 already added `bot/tests`, skip this.

### Step 4 — verify plumbing with a throwaway collection check

Create `bot/tests/test_wiring.py`:

```python
"""Plumbing check: the aiwip_bot package and bot/tests are wired into pytest."""
import aiwip_bot  # noqa: F401  — import must resolve


def test_package_imports():
    assert aiwip_bot is not None
```

Run:

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest bot/tests/test_wiring.py -q
```

Expected: exit code `0`, and the summary line shows `1 passed`.

### Step 5 — remove the throwaway test

Delete `bot/tests/test_wiring.py` (it has served its purpose; real tests follow). Re-run to confirm
the dir still collects with no errors:

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest bot/tests -q
```

Expected: exit code `0`. (`no tests ran` is acceptable here — the only assertion is exit 0 with no collection error.)

**Commit (only when the user asks):** `chore: wire aiwip_bot package and bot/tests into pytest`

---

## Task 5.1 — RED: per-chat config write/read round-trips through Redis

**Goal:** an unconfigured chat reads back as not-configured; after saving a config it reads back
configured with the saved destination. This is the storage contract the gate (5.3) depends on.

### Step 1 — write the failing test

Create `bot/tests/test_chat_config.py`:

```python
"""Phase 5 — per-chat onboarding config stored in Redis (configure-before-capture)."""
from aiwip_bot import state
from aiwip_core.redis_client import get_redis

CHAT = 5551001


def _clean(chat: int) -> None:
    get_redis().delete(state.chat_config_key(chat))


def test_unconfigured_chat_reads_as_not_configured():
    _clean(CHAT)
    assert state.is_chat_configured(CHAT) is False
    assert state.get_chat_config(CHAT) is None


def test_set_config_marks_chat_configured_and_round_trips():
    _clean(CHAT)
    state.set_chat_config(CHAT, destination="board:42")
    assert state.is_chat_configured(CHAT) is True
    cfg = state.get_chat_config(CHAT)
    assert cfg is not None
    assert cfg["destination"] == "board:42"
    assert cfg["configured"] is True
    _clean(CHAT)
```

### Step 2 — verify it fails for the right reason

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest bot/tests/test_chat_config.py -q
```

Expected: failure with `AttributeError: module 'aiwip_bot.state' has no attribute 'chat_config_key'`
(or `... 'is_chat_configured'`). That is the right reason — the helpers don't exist yet. Exit code is non-zero.

### Step 3 — GREEN: add the per-chat config helpers to `state.py`

Open `bot/src/aiwip_bot/state.py`. **If the file does not exist yet** (Phase 3 not merged on your
branch), create it with exactly the content below. **If it exists**, append the block delimited by the
`# --- Phase 5: per-chat onboarding config ---` comment to the end of the file and add the two
imports at the top if they are not already present (`import json`, and `from aiwip_core.redis_client import get_redis`).

Full file content for the create case:

```python
"""aiwip_bot.state — Redis-backed bot state.

Holds operational/ephemeral bot state in Redis: per-chat onboarding config
(this phase), and (from other phases) buffers, debounce locks, watermarks,
prefs, and link codes. decode_responses=True is set by the shared client, so
values come back as str and we JSON-encode/decode structured values.
"""
from __future__ import annotations

import json
from typing import Any

from aiwip_core.redis_client import get_redis

# --- Phase 5: per-chat onboarding config ---
# Per-chat configuration written by the configure-before-capture flow (spec §7, §8).
# A chat is "configured" only once a destination is chosen and saved here.
CHAT_CONFIG_PREFIX = "aiwip:botcfg:"


def chat_config_key(chat_id: int) -> str:
    """Redis key holding the per-chat onboarding config JSON."""
    return f"{CHAT_CONFIG_PREFIX}{chat_id}"


def get_chat_config(chat_id: int) -> dict[str, Any] | None:
    """Return the saved per-chat config dict, or None if the chat was never configured."""
    raw = get_redis().get(chat_config_key(chat_id))
    if raw is None:
        return None
    return json.loads(raw)


def is_chat_configured(chat_id: int) -> bool:
    """True only if a config exists for this chat AND its `configured` flag is True."""
    cfg = get_chat_config(chat_id)
    return bool(cfg) and cfg.get("configured") is True


def set_chat_config(
    chat_id: int,
    *,
    destination: str,
    surface_mode: str = "cards",
    debounce_seconds: int | None = None,
    quiet_hours: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist the per-chat config and mark the chat configured. Returns the stored dict.

    `destination` is the chosen board/destination identifier (e.g. "board:42"). The config is
    stored with no TTL — onboarding state must survive bot restarts (spec §7: capture begins only
    after the chat is configured, and stays configured).
    """
    cfg: dict[str, Any] = {
        "destination": destination,
        "surface_mode": surface_mode,
        "debounce_seconds": debounce_seconds,
        "quiet_hours": quiet_hours,
        "configured": True,
    }
    get_redis().set(chat_config_key(chat_id), json.dumps(cfg))
    return cfg


def clear_chat_config(chat_id: int) -> None:
    """Remove a chat's config (used when the bot is removed from a group, or to re-onboard)."""
    get_redis().delete(chat_config_key(chat_id))
```

> If `state.py` already exists from Phase 3, add only: (1) the two imports if missing, and (2) the
> entire block from the `# --- Phase 5: per-chat onboarding config ---` comment downward. Keep all
> Phase-3 functions intact.

### Step 4 — verify it passes

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest bot/tests/test_chat_config.py -q
```

Expected: exit code `0`, summary `2 passed`.

**Commit (only when the user asks):** `feat: per-chat onboarding config in bot Redis state`

---

## Task 5.2 — RED: onboarding prompt is emitted for an unconfigured chat, and saving config marks it configured

**Goal:** the `onboarding` module turns "bot added to a group" into a config prompt (text +
destination picker payload) for an unconfigured chat, and a "destination chosen" callback into a
saved config. No live Telegram I/O — the module returns plain data structures that the Phase-4
sender renders; this keeps onboarding unit-testable against Redis only.

### Step 1 — write the failing test

Create `bot/tests/test_onboarding.py`:

```python
"""Phase 5 — configure-before-capture onboarding flow (spec §7)."""
from aiwip_bot import onboarding, state
from aiwip_core.redis_client import get_redis

CHAT = 5552002


def _clean(chat: int) -> None:
    get_redis().delete(state.chat_config_key(chat))


def test_added_to_unconfigured_group_returns_config_prompt():
    _clean(CHAT)
    prompt = onboarding.on_bot_added_to_group(CHAT)
    assert prompt is not None
    assert "text" in prompt and prompt["text"]
    # the prompt must offer a destination picker action
    actions = prompt["actions"]
    assert any(a["action"] == "choose_destination" for a in actions)
    _clean(CHAT)


def test_added_to_already_configured_group_returns_none():
    _clean(CHAT)
    state.set_chat_config(CHAT, destination="board:7")
    assert onboarding.on_bot_added_to_group(CHAT) is None
    _clean(CHAT)


def test_handle_destination_choice_saves_config_and_marks_configured():
    _clean(CHAT)
    result = onboarding.handle_destination_choice(CHAT, destination="board:99")
    assert result["configured"] is True
    assert result["destination"] == "board:99"
    assert state.is_chat_configured(CHAT) is True
    _clean(CHAT)
```

### Step 2 — verify it fails for the right reason

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest bot/tests/test_onboarding.py -q
```

Expected: failure `ModuleNotFoundError: No module named 'aiwip_bot.onboarding'`. Right reason — the
module doesn't exist. Exit code non-zero.

### Step 3 — GREEN: create the onboarding module

Create `bot/src/aiwip_bot/onboarding.py` with exactly this content:

```python
"""aiwip_bot.onboarding — configure-before-capture flow (design spec §7).

When the bot is added to a group it must first ask which board/destination to log tasks into,
and only after a destination is saved does capture begin. This module is pure data-in/data-out:
it decides *what* to prompt and *what* to persist; the Phase-4 Telegram sender renders the
returned dict into a message + inline keyboard. Keeping it I/O-free makes the gate testable
against Redis alone.
"""
from __future__ import annotations

from typing import Any

from . import state

# User-facing onboarding copy (spec §7 wording).
CONFIG_PROMPT_TEXT = (
    "Чтобы я начал ловить задачи, выберите куда их складывать."
)


def on_bot_added_to_group(chat_id: int) -> dict[str, Any] | None:
    """Return the config prompt for an unconfigured chat, or None if already configured.

    The returned dict shape (rendered by the Phase-4 sender):
        {"text": str, "actions": [{"action": "choose_destination", "label": str}, ...]}
    Returning None means the chat is already configured — do NOT re-prompt.
    """
    if state.is_chat_configured(chat_id):
        return None
    return {
        "text": CONFIG_PROMPT_TEXT,
        "actions": [
            {"action": "choose_destination", "label": "Выбрать борду/назначение"},
        ],
    }


def handle_destination_choice(chat_id: int, *, destination: str) -> dict[str, Any]:
    """Persist the chosen destination, mark the chat configured, and return the stored config.

    After this returns, `state.is_chat_configured(chat_id)` is True and capture may begin
    (the ingest gate, §5.3, will start pushing inbound messages to the extract buffer).
    """
    return state.set_chat_config(chat_id, destination=destination)
```

### Step 4 — verify it passes

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest bot/tests/test_onboarding.py -q
```

Expected: exit code `0`, summary `3 passed`.

**Commit (only when the user asks):** `feat: configure-before-capture onboarding flow for the bot`

---

## Task 5.3 — RED (the gate): unconfigured chat captures nothing; configured chat captures

**Goal:** this is the phase's headline guarantee (spec §7 GATE). `ingest.handle_inbound_message`
must push to `aiwip:botbuf:{chat}` and enqueue a job **only** for a configured chat. For an
unconfigured chat it must push nothing and enqueue nothing — instead it triggers onboarding.

### Step 1 — write the failing test

Create `bot/tests/test_ingest_gate.py`:

```python
"""Phase 5 — configure-before-capture gate in ingest (spec §7 GATE).

GATE: chat NOT configured => message is NOT pushed to the extract buffer and NO job is enqueued.
A configured chat DOES push to the buffer.
"""
from aiwip_bot import ingest, state
from aiwip_core.queue import JOBS_KEY
from aiwip_core.redis_client import get_redis

CHAT = 5553003


def _msg(text: str) -> dict:
    # Minimal inbound-message shape the bot passes to ingest (Phase-3 normalized record).
    return {
        "chat_id": CHAT,
        "message_id": 1001,
        "from_user_id": 700,
        "text": text,
        "date": 1735000000,
    }


def _clean() -> None:
    r = get_redis()
    r.delete(state.chat_config_key(CHAT))
    r.delete(ingest.buffer_key(CHAT))
    r.delete(JOBS_KEY)


def test_unconfigured_chat_does_not_buffer_or_enqueue():
    _clean()
    assert state.is_chat_configured(CHAT) is False

    captured = ingest.handle_inbound_message(_msg("кто-то сделай отчёт"))

    r = get_redis()
    assert r.llen(ingest.buffer_key(CHAT)) == 0  # nothing captured
    assert r.llen(JOBS_KEY) == 0                  # no job enqueued
    assert captured is False                      # gate reports "not captured"
    _clean()


def test_unconfigured_chat_triggers_onboarding_prompt():
    _clean()
    prompt = ingest.handle_inbound_message_with_onboarding(_msg("привет"))
    # gate closed => the caller is handed an onboarding prompt to send instead of capturing
    assert prompt is not None
    assert prompt["actions"][0]["action"] == "choose_destination"
    assert get_redis().llen(ingest.buffer_key(CHAT)) == 0
    _clean()


def test_configured_chat_buffers_the_message():
    _clean()
    state.set_chat_config(CHAT, destination="board:1")

    captured = ingest.handle_inbound_message(_msg("надо подготовить макет к пятнице"))

    assert captured is True
    assert get_redis().llen(ingest.buffer_key(CHAT)) == 1  # exactly one buffered record
    _clean()
```

> Note: this test asserts on the **buffer** push and **job** enqueue only. It does **not** assert
> the debounce/enqueue timing (that is Phase 6's concern). `handle_inbound_message` here pushes to
> the buffer when configured; whether/when a job is enqueued for the configured path is left to the
> Phase-3/6 debounce logic. For the unconfigured path we assert **both** buffer == 0 and jobs == 0,
> which is the gate's hard contract.

### Step 2 — verify it fails for the right reason

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest bot/tests/test_ingest_gate.py -q
```

Expected: failure `ModuleNotFoundError: No module named 'aiwip_bot.ingest'` (if Phase 3 not merged)
or `AttributeError: module 'aiwip_bot.ingest' has no attribute 'handle_inbound_message_with_onboarding'`
(if Phase 3's `ingest.py` exists but lacks the gate). Either is the right reason. Exit code non-zero.

### Step 3 — GREEN: add the configure-before-capture gate to `ingest.py`

Open `bot/src/aiwip_bot/ingest.py`.

**If the file does not exist** (Phase 3 not merged on your branch), create it with exactly the
content below.

**If it exists from Phase 3**, do this surgically:
1. Ensure `from . import onboarding, state` is imported (add `onboarding` and `state` to the existing import if needed).
2. Add the `buffer_key` helper if it is not already defined (match the Phase-3 buffer key name `aiwip:botbuf:{chat}`).
3. In the Phase-3 `handle_inbound_message`, insert the **gate guard as the very first statement**:
   `if not state.is_chat_configured(message["chat_id"]): return False` — before any buffer push or
   enqueue. Keep the rest of Phase-3's body for the configured path.
4. Add `handle_inbound_message_with_onboarding` exactly as shown.

Full file content for the create case:

```python
"""aiwip_bot.ingest — inbound message capture with the configure-before-capture gate.

Flow (design spec §4.2 data flow, §7 gate):
    inbound message
      -> CONFIGURE GATE: chat configured?  (state.is_chat_configured)
           no  -> capture NOTHING (no buffer push, no job); onboarding handles it
           yes -> LPUSH aiwip:botbuf:{chat}  (Phase 6 drains it via BotApiConnector -> run_sync)
The gate is the single point that enforces the owner's rule: capture begins only after a chat is
configured. Debounce / job-enqueue timing for the configured path is owned by Phase 3/6; this
module only guarantees the gate and the buffer push.
"""
from __future__ import annotations

import json
from typing import Any

from aiwip_core.redis_client import get_redis

from . import onboarding, state

# Per-chat inbound buffer (Redis list). Phase 6's BotApiConnector drains this in ascending id order.
BUFFER_PREFIX = "aiwip:botbuf:"


def buffer_key(chat_id: int) -> str:
    """Redis key for the per-chat inbound message buffer."""
    return f"{BUFFER_PREFIX}{chat_id}"


def handle_inbound_message(message: dict[str, Any]) -> bool:
    """Capture an inbound group message, gated on the chat being configured.

    Returns True if the message was captured (buffered), False if the gate blocked it because the
    chat is not yet configured. GATE: an unconfigured chat pushes NOTHING to the buffer and enqueues
    NO job.
    """
    chat_id = message["chat_id"]
    if not state.is_chat_configured(chat_id):
        return False  # configure-before-capture: drop on the floor, onboarding handles the chat
    get_redis().rpush(buffer_key(chat_id), json.dumps(message))
    return True


def handle_inbound_message_with_onboarding(message: dict[str, Any]) -> dict[str, Any] | None:
    """Capture if configured; otherwise return an onboarding prompt for the caller to send.

    Returns:
        None  -> message was captured (chat configured), nothing else to do.
        dict  -> the chat is not configured; this is the onboarding prompt to send into the group.
    """
    captured = handle_inbound_message(message)
    if captured:
        return None
    return onboarding.on_bot_added_to_group(message["chat_id"])
```

> Surgical-edit reminder (existing-file case): the **only** new behavior this phase introduces in
> `ingest.py` is (a) the gate guard at the top of `handle_inbound_message` and (b) the new
> `handle_inbound_message_with_onboarding`. Do not alter Phase-3 debounce/enqueue code on the
> configured path.

### Step 4 — verify it passes

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest bot/tests/test_ingest_gate.py -q
```

Expected: exit code `0`, summary `3 passed`.

**Commit (only when the user asks):** `feat: configure-before-capture gate in bot ingest`

---

## Task 5.4 — RED: removing the bot from a group clears config so capture stops

**Goal:** the gate must be reversible. When the bot is removed from a group (or the chat is
re-onboarded), its config is cleared and the gate closes again — a subsequent message captures
nothing until reconfigured. This protects against capturing for a group the team has revoked consent
for (spec §6.3 consent posture, §13 "always-listening" risk).

### Step 1 — write the failing test

Append to `bot/tests/test_onboarding.py`:

```python
def test_removed_from_group_clears_config_and_closes_gate():
    from aiwip_bot import ingest

    CHAT2 = 5552099
    r = get_redis()
    r.delete(state.chat_config_key(CHAT2))
    r.delete(ingest.buffer_key(CHAT2))

    state.set_chat_config(CHAT2, destination="board:5")
    assert state.is_chat_configured(CHAT2) is True

    onboarding.on_bot_removed_from_group(CHAT2)

    assert state.is_chat_configured(CHAT2) is False
    # gate is closed again: a new message captures nothing
    captured = ingest.handle_inbound_message(
        {"chat_id": CHAT2, "message_id": 1, "from_user_id": 1, "text": "x", "date": 1}
    )
    assert captured is False
    assert r.llen(ingest.buffer_key(CHAT2)) == 0

    r.delete(state.chat_config_key(CHAT2))
    r.delete(ingest.buffer_key(CHAT2))
```

### Step 2 — verify it fails for the right reason

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest bot/tests/test_onboarding.py::test_removed_from_group_clears_config_and_closes_gate -q
```

Expected: failure `AttributeError: module 'aiwip_bot.onboarding' has no attribute 'on_bot_removed_from_group'`.
Right reason. Exit code non-zero.

### Step 3 — GREEN: add the removal handler to `onboarding.py`

Add this function to the end of `bot/src/aiwip_bot/onboarding.py`:

```python
def on_bot_removed_from_group(chat_id: int) -> None:
    """Clear a chat's config when the bot is removed (or to re-onboard).

    Closes the configure-before-capture gate again: until the chat is reconfigured, inbound
    messages capture nothing. Honors team-consent reversibility (spec §6.3, §13).
    """
    state.clear_chat_config(chat_id)
```

### Step 4 — verify the new test passes and the whole onboarding file is green

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest bot/tests/test_onboarding.py -q
```

Expected: exit code `0`, summary `4 passed`.

**Commit (only when the user asks):** `feat: clear per-chat config when bot leaves group (reversible gate)`

---

## Task 5.5 — Full-phase verification (fresh evidence, Iron Law §1.3)

**Goal:** prove the whole phase is green and the existing suite is unaffected. No new code.

### Step 1 — run the entire bot suite

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest bot/tests -q
```

Expected: exit code `0`. Summary shows `9 passed` (Task 5.1: 2, Task 5.2: 3, Task 5.3: 3, Task 5.4: 1).

### Step 2 — run the full repo suite to confirm zero regressions

```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest -q
```

Expected: exit code `0`. The pre-existing ~94-test baseline (core/api/worker) stays green; the 9 new
bot tests are added on top. Read the summary line; confirm `0 failed` and `0 errors`. If Postgres is
not reachable, the core/api/worker DB-backed tests will error — start Postgres
(`docker compose up -d postgres`) and re-run; the **bot** tests in this phase do not need Postgres.

### Step 3 — record the evidence

In your hand-off note, paste the final pytest summary line from Step 2 (the actual numbers), not a
paraphrase. Do not claim completion without this line.

**Commit (only when the user asks):** none — this task adds no code.

---

## SELF-REVIEW CHECKLIST

**Spec coverage (design §7, §2 onboarding rule):**
- [x] Bot added to group → detect not-configured → prompt (`onboarding.on_bot_added_to_group`, Task 5.2).
- [x] Prompt offers a board/destination picker (`choose_destination` action, Task 5.2).
- [x] Save per-chat config in Redis (`state.set_chat_config` → `aiwip:botcfg:{chat}`, Task 5.1).
- [x] Mark configured (`configured: True` flag; `state.is_chat_configured`, Task 5.1).
- [x] Capture begins only after configured (gate in `ingest.handle_inbound_message`, Task 5.3).
- [x] **GATE RED test:** unconfigured chat → buffer == 0 AND jobs == 0 AND `captured is False` (Task 5.3); configured chat → buffer == 1 (Task 5.3).
- [x] Per-chat config in **Redis** (no schema change), per spec §7/§8 — key `aiwip:botcfg:{chat}`.
- [x] Reversibility / consent: removal clears config and re-closes the gate (Task 5.4; spec §6.3, §13).

**Zero placeholders:** no "TBD"/"TODO"/"add validation"/"handle edge cases"/"similar to Task N"/"etc."/"and so on" appear in this plan. Every code block is complete and runnable.

**Type / name consistency with other phases:**
- `aiwip:botbuf:{chat}` (buffer) and `aiwip:botlock:{chat}` (lock) match spec §8 and Phase 3/6 ownership; this phase only *pushes to* `botbuf` (drained by Phase 6's `BotApiConnector`) and never touches `botlock`.
- `aiwip:botcfg:{chat}` is introduced **by this phase** (spec §8 lists per-chat config among the new Redis prefixes); no other phase owns it.
- Reuses `aiwip_core.queue.JOBS_KEY` / `enqueue_sync` verbatim — no new queue surface.
- Reuses `aiwip_core.redis_client.get_redis()` (`decode_responses=True`) — values JSON-encoded/decoded, matching the worker's `queue.py` JSON convention.
- `state.py` / `ingest.py` are the Phase-3 modules (spec §10); this phase **adds** functions, does not rename or remove Phase-3/4 symbols. Onboarding I/O-free dict shape (`{"text", "actions"}`) is rendered by the Phase-4 sender (`cards.py`/`handlers.py`).
- No new DB column, no `CandidateOut` change, no API endpoint — those belong to Phases 1/2/6. This phase is Redis-only and does not touch host production frontend or API files (spec §11.3 boundary: only `frontend-implementation`/host editors touch production; the bot package is the bot-impl surface).

**Dependency notes:**
- **Hard runtime dependency:** a reachable **local Redis** (`redis://localhost:6379/0`). Verified live during authoring (`redis-cli ping` → `PONG`).
- **No Postgres / OpenAI / live Telegram** needed for any Task 5.x test.
- **Phase-3 dependency:** `bot/` package + `state.py` + `ingest.py` skeleton. If Phase 3 is not yet merged on the branch, Task 5.0 + the "create case" code blocks make the package importable and the files complete; if Phase 3 is merged, follow the "existing-file" surgical instructions (add the marked blocks only).
- **Phase-4 dependency:** the message **sender** that renders the `{"text", "actions"}` dict into a Telegram message + inline keyboard. This phase returns the data structure; it does not send. If Phase 4's render contract differs, adapt the dict keys to Phase 4's and note the deviation — the gate logic (5.3) is independent of the render shape.
- **Phase-6 consumer:** Phase 6's `BotApiConnector` drains `aiwip:botbuf:{chat}` in ascending id order; this phase pushes records via `RPUSH` (ascending append) so the connector's "ascending id" drain holds when messages arrive in order. Phase 6 owns dedup/debounce/job-enqueue for the configured path.
