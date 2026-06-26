# Phase 6 — Real-time ingestion + Telethon cutover

> **Source of truth:** `docs/specs/2026-06-26-bot-first-capture-layer-design.md`
> (this plan implements §4.1, §4.2, §6.3, §8 rows for `ConnectorType`/Redis keys, and
> Decisions §16.1 + §16.2). This is the **last** phase: it turns on forward-only bot
> capture and then **removes Telethon and the 6h scheduler** so the bot is the single writer.
>
> **Owner / model routing (design §14):** worker-impl (Opus), one production editor, surgical.
> **Iron Laws that bind this phase:** TDD (every task Red→Green), precision-over-recall
> (the `messages_saved>0` extraction gate is preserved unchanged), human-in-the-loop
> (capture still lands as a `Candidate`, never a `WorkItem`), security-first, surgical changes.

---

## 0. Orientation for an implementer with ZERO codebase context

Read these before starting. Absolute paths under `/Users/eduardshatalov/Documents/telegram-task-bot`.

- **Connector contract** — `worker/src/aiwip_worker/connectors/base.py`. The `Connector`
  Protocol has exactly one method:
  `fetch_messages(self, chat_external_id: int, after_message_id: int | None = None, limit: int = 200) -> list[FetchedMessage]`
  (base.py:33-37). `FetchedMessage` is a dataclass with fields
  `external_message_id: int`, `sender_external_id: int | None`, `sender_username: str | None`,
  `sender_display_name: str | None`, `text: str | None`, `sent_at: dt.datetime`,
  `raw: dict`, `message_type: str = "text"`, `attachments: list` (base.py:16-26).
- **Reference connector** — `worker/src/aiwip_worker/connectors/fake.py` shows the simplest
  possible implementation (sort ascending, filter `> after_message_id`, slice `[:limit]`).
- **Persist path** — `worker/src/aiwip_worker/sync.py` `run_sync` (sync.py:51-143). It calls
  `connector.fetch_messages(chat.external_chat_id, state.last_external_message_id, batch_limit)`
  (sync.py:72), dedups on `(chat_id, external_message_id)` (sync.py:74-87), advances
  `SyncState.last_external_message_id` to `max_id` (sync.py:116). **Do not modify `run_sync`.**
- **Pipeline + gate** — `worker/src/aiwip_worker/consumer.py`. `_build_connector()`
  (consumer.py:28-29) returns `TelegramConnector()` today. `run_pipeline` runs the
  `messages_saved>0` extraction gate (consumer.py:76). `process_job` matches job type
  `"telegram.sync"` (consumer.py:90). **Do not change the gate.**
- **Scheduler** — `worker/src/aiwip_worker/main.py`. The 6h scheduler is the
  `if now - last_schedule >= settings.sync_interval_seconds:` block (main.py:51-58) which
  calls `consumer.enqueue_scheduled_syncs` (consumer.py:116-120).
- **Queue helpers** — `core/src/aiwip_core/queue.py`. `enqueue`/`dequeue` wrap the Redis
  list `aiwip:jobs` (queue.py:15-29); `enqueue_sync` (queue.py:36-39) pushes a
  `{"type":"telegram.sync","chat_id":...,"trigger":...,"user_id":...,"attempts":...}` job.
- **Redis client** — `core/src/aiwip_core/redis_client.py` `get_redis()` returns a
  `redis.Redis` with `decode_responses=True` (strings, not bytes).
- **Models** — `core/src/aiwip_core/models.py`. `ConnectorType` enum (models.py:51-56,
  currently `telegram/slack/email/whatsapp/discord`). `Chat.connector_type` (models.py:252).
  Native PG enums are built via `_pg_enum(...)` (models.py:193-195) storing member *values*.
- **Alembic head** — current head is revision `2fe660361238`
  (`core/alembic/versions/2fe660361238_add_users_password_hash.py`), which revises
  `a050622bac2d`. A new migration must set `down_revision = '2fe660361238'`. `alembic.ini`
  lives at `core/alembic.ini`.
- **Tests** — `worker/tests/` (e.g. `test_sync.py`, `test_consumer.py`, `test_queue.py`,
  `test_e2e.py`). Root `conftest.py` forces `localhost` for DB/Redis and provides `db`
  (savepoint-isolated session) and `engine` fixtures. `pytest.ini` sets
  `testpaths = core/tests api/tests worker/tests`. Tests require a reachable local
  Postgres (`aiwip_test`) and Redis (db 0).

**Test runner used in every verify step below** (run from the repo root):
```
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest <path> -q
```
Local Postgres + Redis must be up (`docker compose up -d postgres redis`). All
container checks: rebuild first — `docker compose build worker && docker compose up -d worker`
(stale-image gotcha).

**Bot package status:** Phases 3–5 created `bot/src/aiwip_bot/` (config, state, main, cards,
handlers, authz, onboarding). Phase 6 adds **one** new bot module, `bot/src/aiwip_bot/ingest.py`,
and the bot's `bot/tests/` directory already exists. The buffer/notify Redis-key helpers live
in **core** (`core/src/aiwip_core/queue.py`) so both the worker (drain) and the bot (push) share
one definition — mirroring how `JOBS_KEY`/`enqueue_sync` are already shared there.

---

## Task ordering rationale

Build capture **first** (6.1–6.9) while Telethon is still present and the suite is green,
proving the new path end-to-end. Only **then** cut over (6.10–6.12): remove Telethon and the
scheduler. This is the design §14 sequencing note — riskiest change (removal) ships last on a
proven surface.

---

## Task 6.1 — Add the buffer + notify Redis-key helpers to core queue (Red→Green)

**Goal:** introduce the shared Redis keys `aiwip:botbuf:{chat}` (the per-chat ingest buffer)
and `aiwip:bot:notify` (the worker→bot candidate notification list), plus push/length/notify
helpers, in `core/src/aiwip_core/queue.py`. These are the contract both the bot (writer) and
worker (reader) depend on.

### Red — write the failing test

Create `core/tests/test_queue_botbuf.py`:

```python
"""Phase 6 — bot ingest buffer + notify queue helpers (real local Redis)."""
import json

from aiwip_core import queue
from aiwip_core.redis_client import get_redis


def test_botbuf_key_is_per_chat():
    assert queue.botbuf_key(555) == "aiwip:botbuf:555"


def test_push_botbuf_appends_and_len_counts():
    r = get_redis()
    r.delete(queue.botbuf_key(900))
    queue.push_botbuf(900, {"external_message_id": 1, "text": "hi"})
    queue.push_botbuf(900, {"external_message_id": 2, "text": "yo"})
    assert queue.botbuf_len(900) == 2
    # stored as JSON, in push order (LPUSH/RPUSH detail verified by the drain test, 6.2)
    raw = r.lrange(queue.botbuf_key(900), 0, -1)
    assert {json.loads(x)["external_message_id"] for x in raw} == {1, 2}
    r.delete(queue.botbuf_key(900))


def test_notify_roundtrip():
    r = get_redis()
    r.delete(queue.NOTIFY_KEY)
    queue.enqueue_notify(42)
    msg = queue.dequeue_notify(timeout=2)
    assert msg == {"type": "bot.notify", "candidate_id": 42}
    assert r.llen(queue.NOTIFY_KEY) == 0
    r.delete(queue.NOTIFY_KEY)
```

Run it and confirm it fails for the right reason (helpers don't exist yet):
```
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest core/tests/test_queue_botbuf.py -q
```
**Expected:** failure with `AttributeError: module 'aiwip_core.queue' has no attribute 'botbuf_key'`
(or `push_botbuf`/`NOTIFY_KEY`). Exit code non-zero.

### Green — add the helpers

Edit `core/src/aiwip_core/queue.py`. After the existing `JOBS_KEY = "aiwip:jobs"` line
(queue.py:15) add the two new key constants, and append the helper functions at the end of the
file (after `enqueue_sync`, queue.py:39).

Add directly below `JOBS_KEY = "aiwip:jobs"`:
```python
NOTIFY_KEY = "aiwip:bot:notify"  # worker → bot: {"type":"bot.notify","candidate_id":int}
BOTBUF_PREFIX = "aiwip:botbuf:"  # per-chat inbound buffer: aiwip:botbuf:{external_chat_id}
```

Append at the end of the file:
```python
def botbuf_key(external_chat_id: int) -> str:
    return f"{BOTBUF_PREFIX}{external_chat_id}"


def push_botbuf(external_chat_id: int, record: dict) -> None:
    """Append one inbound message record (forward-only). RPUSH keeps arrival order."""
    get_redis().rpush(botbuf_key(external_chat_id), json.dumps(record))


def botbuf_len(external_chat_id: int) -> int:
    return int(get_redis().llen(botbuf_key(external_chat_id)))


def enqueue_notify(candidate_id: int) -> None:
    get_redis().lpush(NOTIFY_KEY, json.dumps({"type": "bot.notify", "candidate_id": candidate_id}))


def dequeue_notify(timeout: int = 5) -> dict | None:
    try:
        res = get_redis().brpop(NOTIFY_KEY, timeout=timeout)
    except redis.exceptions.TimeoutError:
        return None
    if res is None:
        return None
    return json.loads(res[1])
```

Run it and confirm pass:
```
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest core/tests/test_queue_botbuf.py -q
```
**Expected:** `3 passed`. Exit code 0.

### Commit (only if the user asks)
`feat: add bot ingest buffer + notify queue helpers to core`

---

## Task 6.2 — `BotApiConnector` drains the buffer ascending (Red→Green)

**Goal:** a `Connector` implementation that reads `aiwip:botbuf:{chat}` and returns
`FetchedMessage`s sorted by `external_message_id` ascending, filtered to `> after_message_id`,
capped at `limit` — so `run_sync` is unchanged. **The buffer is consumed (drained) as part of
the fetch** so the same message is never re-ingested.

### Red — write the failing test

Create `worker/tests/test_bot_api_connector.py`:

```python
"""Phase 6 — BotApiConnector drains the Redis ingest buffer (real local Redis)."""
import datetime as dt

from aiwip_core import queue
from aiwip_core.redis_client import get_redis
from aiwip_worker.connectors.bot_api import BotApiConnector


def _rec(i: int, text: str = "hi") -> dict:
    return {
        "external_message_id": i,
        "sender_external_id": 100 + i,
        "sender_username": "u",
        "sender_display_name": "U",
        "text": text,
        "sent_at": dt.datetime(2026, 6, 1, tzinfo=dt.timezone.utc).isoformat(),
        "raw": {"id": i},
        "message_type": "text",
        "attachments": [],
    }


def test_drains_ascending_and_caps_limit():
    chat = 4001
    r = get_redis()
    r.delete(queue.botbuf_key(chat))
    # push out of order to prove sorting
    for rec in (_rec(3), _rec(1), _rec(2)):
        queue.push_botbuf(chat, rec)
    out = BotApiConnector().fetch_messages(chat, after_message_id=None, limit=2)
    assert [m.external_message_id for m in out] == [1, 2]  # ascending, capped at 2
    assert out[0].text == "hi" and out[0].sender_username == "u"
    assert isinstance(out[0].sent_at, dt.datetime)
    r.delete(queue.botbuf_key(chat))


def test_filters_after_message_id_and_drains():
    chat = 4002
    r = get_redis()
    r.delete(queue.botbuf_key(chat))
    for rec in (_rec(1), _rec(2), _rec(3)):
        queue.push_botbuf(chat, rec)
    conn = BotApiConnector()
    out = conn.fetch_messages(chat, after_message_id=1, limit=200)
    assert [m.external_message_id for m in out] == [2, 3]
    # buffer is fully drained by the fetch — a second fetch returns nothing
    assert conn.fetch_messages(chat, after_message_id=1, limit=200) == []
    assert queue.botbuf_len(chat) == 0
    r.delete(queue.botbuf_key(chat))
```

Run and confirm failure for the right reason (module missing):
```
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest worker/tests/test_bot_api_connector.py -q
```
**Expected:** `ModuleNotFoundError: No module named 'aiwip_worker.connectors.bot_api'`. Exit non-zero.

### Green — create the connector

Create `worker/src/aiwip_worker/connectors/bot_api.py`:

```python
"""Bot API connector: drains the Redis ingest buffer the bot fills (forward-only).

The bot service RPUSHes raw inbound records to aiwip:botbuf:{chat}; this connector drains
that list, returns them as FetchedMessages in ascending external_message_id order, and lets
the EXISTING run_sync path dedup + persist them. No history pull, no network — the bot already
captured everything forward-only.
"""
from __future__ import annotations

import datetime as dt
import json

from aiwip_core import queue
from aiwip_core.redis_client import get_redis

from .base import FetchedAttachment, FetchedMessage


def _parse_sent_at(value) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return value
    return dt.datetime.fromisoformat(value)


class BotApiConnector:
    def fetch_messages(
        self, chat_external_id: int, after_message_id: int | None = None, limit: int = 200
    ) -> list[FetchedMessage]:
        key = queue.botbuf_key(chat_external_id)
        r = get_redis()
        raw = r.lrange(key, 0, -1)
        r.delete(key)  # drain: this buffer is forward-only, never re-read
        records = [json.loads(x) for x in raw]
        records.sort(key=lambda rec: rec["external_message_id"])
        out: list[FetchedMessage] = []
        for rec in records:
            mid = rec["external_message_id"]
            if after_message_id is not None and mid <= after_message_id:
                continue
            out.append(
                FetchedMessage(
                    external_message_id=mid,
                    sender_external_id=rec.get("sender_external_id"),
                    sender_username=rec.get("sender_username"),
                    sender_display_name=rec.get("sender_display_name"),
                    text=rec.get("text"),
                    sent_at=_parse_sent_at(rec["sent_at"]),
                    raw=rec.get("raw", {}),
                    message_type=rec.get("message_type", "text"),
                    attachments=[
                        FetchedAttachment(
                            attachment_type=a["attachment_type"],
                            file_name=a.get("file_name"),
                            mime_type=a.get("mime_type"),
                        )
                        for a in rec.get("attachments", [])
                    ],
                )
            )
            if len(out) >= limit:
                break
        return out
```

Run and confirm pass:
```
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest worker/tests/test_bot_api_connector.py -q
```
**Expected:** `2 passed`. Exit code 0.

> **Note on the drain + cap interaction:** the buffer is drained in full on each fetch, then
> the in-memory list is filtered/capped. With the design's debounce (≤1 in-flight job per chat,
> §4.2) the buffer is sized to one debounce window, so `limit` (default 200) is not exceeded in
> practice; any overflow beyond `limit` is dropped only after being removed from Redis. This is
> acceptable for MVP forward-only capture (design §3 accepts gap-on-downtime) and is the same
> 200-cap the Telethon path used (telegram.py:43). It is called out here so the cutover review
> can decide whether to raise `batch_limit` for very bursty chats.

### Commit (only if the user asks)
`feat: add BotApiConnector draining the Redis ingest buffer`

---

## Task 6.3 — `run_sync` dedup holds for the bot connector (Red→Green, regression guard)

**Goal:** prove the existing dedup invariant (sync.py:74-87) survives when the source is the
buffer connector — re-pushing an already-saved id saves 0. This is a **regression test only**;
no production change is expected (it should pass on the 6.2 code). If it fails, the buffer drain
broke dedup and must be fixed before proceeding.

### Red — write the test

Create `worker/tests/test_bot_api_sync.py`:

```python
"""Phase 6 — BotApiConnector through the real run_sync persist path (dedup + state)."""
import datetime as dt

from aiwip_core import models as m
from aiwip_core import queue
from aiwip_core.redis_client import get_redis
from aiwip_worker import sync
from aiwip_worker.connectors.bot_api import BotApiConnector


def _rec(i: int) -> dict:
    return {
        "external_message_id": i, "sender_external_id": i, "sender_username": "u",
        "sender_display_name": "U", "text": "hi",
        "sent_at": dt.datetime(2026, 6, 1, tzinfo=dt.timezone.utc).isoformat(),
        "raw": {"id": i}, "message_type": "text", "attachments": [],
    }


def _chat(db, ext: int) -> m.Chat:
    c = m.Chat(connector_type=m.ConnectorType.telegram, external_chat_id=ext, title="c")
    db.add(c)
    db.flush()
    return c


def test_run_sync_with_bot_connector_dedups(db):
    ext = 4100
    r = get_redis()
    r.delete(queue.botbuf_key(ext))
    chat = _chat(db, ext)

    for rec in (_rec(1), _rec(2)):
        queue.push_botbuf(ext, rec)
    run1 = sync.run_sync(db, BotApiConnector(), chat, m.SyncTriggerType.manual)
    assert run1.messages_saved == 2

    # bot re-delivers an old id (1) plus a new one (3); dedup must keep only 3
    for rec in (_rec(1), _rec(3)):
        queue.push_botbuf(ext, rec)
    run2 = sync.run_sync(db, BotApiConnector(), chat, m.SyncTriggerType.scheduled)
    assert run2.messages_saved == 1
    assert db.query(m.Message).filter_by(chat_id=chat.id).count() == 3
    state = db.query(m.SyncState).filter_by(chat_id=chat.id).one()
    assert state.last_external_message_id == 3
    r.delete(queue.botbuf_key(ext))
```

Run:
```
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest worker/tests/test_bot_api_sync.py -q
```
**Expected:** `1 passed` (dedup already holds via `run_sync`). Exit code 0. If it does NOT
pass, stop and fix 6.2 (the `after_message_id` filter or the ascending sort) before continuing.

### Commit (only if the user asks)
`test: guard run_sync dedup through BotApiConnector`

---

## Task 6.4 — `_build_connector` becomes a factory on `Chat.connector_type` (Red→Green)

**Goal:** `consumer.process_job` must pick the connector based on the chat's
`connector_type`. Telethon for `ConnectorType.telegram`, `BotApiConnector` for the new
`ConnectorType.telegram_bot` (added in 6.7). Because this task runs *before* the enum value
exists, the test drives the factory by **value**, asserting branch selection by string.

> The current `_build_connector()` (consumer.py:28-29) takes no args and always returns
> `TelegramConnector()`. We replace it with a factory keyed on the connector type, and update
> the one call site in `process_job` (consumer.py:97) to pass the chat's type. `consume_once`
> (consumer.py:108-113) currently passes `connector_factory=_build_connector` as a default — we
> keep that parameter name but the default becomes the factory.

### Red — write the failing test

Create `worker/tests/test_connector_factory.py`:

```python
"""Phase 6 — connector factory keyed on Chat.connector_type."""
from aiwip_worker import consumer
from aiwip_worker.connectors.bot_api import BotApiConnector


def test_factory_returns_bot_connector_for_telegram_bot():
    conn = consumer.build_connector("telegram_bot")
    assert isinstance(conn, BotApiConnector)


def test_factory_returns_telethon_for_telegram(monkeypatch):
    # avoid requiring Telegram credentials in the test: stub the Telethon connector
    sentinel = object()
    monkeypatch.setattr(consumer, "TelegramConnector", lambda: sentinel)
    assert consumer.build_connector("telegram") is sentinel


def test_factory_rejects_unknown_type():
    import pytest
    with pytest.raises(ValueError):
        consumer.build_connector("slack")
```

Run and confirm failure (no `build_connector`):
```
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest worker/tests/test_connector_factory.py -q
```
**Expected:** `AttributeError: module 'aiwip_worker.consumer' has no attribute 'build_connector'`.
Exit non-zero.

### Green — add the factory

Edit `worker/src/aiwip_worker/consumer.py`.

1. Add the import next to the existing connector import (consumer.py:21-22). Below
   `from .connectors.telegram import TelegramConnector` add:
   ```python
   from .connectors.bot_api import BotApiConnector
   ```

2. Replace `_build_connector` (consumer.py:28-29):
   ```python
   def _build_connector() -> Connector:
       return TelegramConnector()
   ```
   with a factory plus a backward-compatible default:
   ```python
   def build_connector(connector_type: str) -> Connector:
       """Pick the transport for a chat. A chat is owned by exactly one transport (design §4.2)."""
       if connector_type == "telegram_bot":
           return BotApiConnector()
       if connector_type == "telegram":
           return TelegramConnector()
       raise ValueError(f"no connector for connector_type={connector_type!r}")
   ```

   > `_build_connector` is referenced as the default for `process_job(connector_factory=...)`
   > and `consume_once(connector_factory=...)`. Those defaults are reworked in step 3, so the
   > old zero-arg `_build_connector` is no longer needed and is removed in this step.

3. **Resolve the chat ONCE, then thread the chat + connector into `run_pipeline`.** The chat
   row's `connector_type` is the single source of truth and must be read exactly once per job,
   **before** connector selection. `run_pipeline` must NOT independently re-create the chat with
   the default connector type (today it calls `get_or_create_chat(db, chat_id)` internally at
   consumer.py:73 with a hard-coded `ConnectorType.telegram` default — that second resolution is
   what makes a fresh bot chat get created as `telegram`). Two coordinated edits:

   **(a) `run_pipeline` accepts the already-resolved `chat` and stops re-resolving it.** Change
   `run_pipeline`'s signature to take a `chat: Chat` (the row `process_job` resolved) instead of
   re-deriving it from `chat_id`, and DELETE the internal `get_or_create_chat(db, chat_id)` call
   (consumer.py:73). Every place inside `run_pipeline` that used the locally-resolved chat now
   uses the passed-in `chat` (so `chat.id`, `chat.external_chat_id`, etc. are unchanged). Tests
   that call `run_pipeline` directly with a `chat_id` must be updated to pass a resolved `chat`
   row instead (the 6.5/6.9 tests in this plan already create/resolve the chat first).

   **(b) `process_job` resolves the chat once and builds the connector from `chat.connector_type`.**
   Current code (consumer.py:89-98):
   ```python
   def process_job(job: dict, connector_factory=_build_connector, session_factory=None, llm_client=None) -> None:
       if job.get("type") != "telegram.sync":
           logger.warning("unknown job type: %s", job.get("type"))
           return
       sf = session_factory or get_sessionmaker()
       chat_id = job["chat_id"]
       trigger = SyncTriggerType(job.get("trigger", "manual"))
       with sf() as db:
           run = run_pipeline(db, connector_factory(), chat_id, trigger, job.get("user_id"), llm_client=llm_client)
           status = run.status
   ```
   becomes:
   ```python
   def process_job(job: dict, connector_factory=None, session_factory=None, llm_client=None) -> None:
       if job.get("type") != "telegram.sync":
           logger.warning("unknown job type: %s", job.get("type"))
           return
       sf = session_factory or get_sessionmaker()
       chat_id = job["chat_id"]
       trigger = SyncTriggerType(job.get("trigger", "manual"))
       with sf() as db:
           chat = get_or_create_chat(db, chat_id)
           connector = connector_factory() if connector_factory else build_connector(chat.connector_type.value)
           run = run_pipeline(db, connector, chat, trigger, job.get("user_id"), llm_client=llm_client)
           status = run.status
   ```
   > **Single canonical rule every Phase-6 task adopts:** the chat row's `connector_type` is the
   > source of truth and is read **exactly once per job** (`get_or_create_chat` in `process_job`)
   > before connector selection; `run_pipeline` receives that resolved `chat` and must not
   > re-create the chat with the default `connector_type`. `chat.connector_type` is the
   > `ConnectorType` enum and `.value` is the lowercase token (`"telegram"`/`"telegram_bot"`).
   > Tests still inject a connector via `connector_factory=` (e.g. `FakeConnector`), so the
   > `connector_factory() if connector_factory else ...` branch keeps existing consumer/e2e tests
   > working — but those tests now resolve the chat (the seam moved from `run_pipeline` to
   > `process_job`), so any test calling `run_pipeline` directly must pass a `chat` row, not a
   > bare `chat_id` (the 6.5/6.9 tests already do).

4. Update `consume_once` (consumer.py:108-113):
   ```python
   def consume_once(timeout: int = 5, connector_factory=_build_connector) -> bool:
       job = queue.dequeue(timeout=timeout)
       if job is None:
           return False
       process_job(job, connector_factory=connector_factory)
       return True
   ```
   becomes:
   ```python
   def consume_once(timeout: int = 5, connector_factory=None) -> bool:
       job = queue.dequeue(timeout=timeout)
       if job is None:
           return False
       process_job(job, connector_factory=connector_factory)
       return True
   ```

Run the factory test and the consumer regression suite:
```
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest worker/tests/test_connector_factory.py worker/tests/test_consumer.py worker/tests/test_e2e.py -q
```
**Expected:** all pass (factory tests + existing consumer/e2e tests unchanged). Exit code 0.

### Commit (only if the user asks)
`feat: make consumer pick the connector by Chat.connector_type`

---

## Task 6.5 — Worker emits `bot.notify {candidate_id}` for new candidates (Red→Green)

**Goal:** after extraction produces candidates, the worker enqueues one `bot.notify` per new
candidate id onto `aiwip:bot:notify` so the bot can render confirm cards. `run_pipeline` already
calls `extract.extract_candidates` (consumer.py:78), which **returns the list of created
`Candidate`s** (confirmed in `worker/tests/test_e2e.py:45` — `created = extract.extract_candidates(...)`).
We capture that return value and notify.

### Red — write the failing test

Create `worker/tests/test_notify_emit.py`:

```python
"""Phase 6 — run_pipeline emits bot.notify for each new candidate."""
import datetime as dt

from aiwip_core import models as m
from aiwip_core import queue
from aiwip_core.redis_client import get_redis
from aiwip_worker import consumer
from aiwip_worker.connectors.base import FetchedMessage
from aiwip_worker.connectors.fake import FakeConnector
from aiwip_worker.llm.client import FakeLLMClient

BASE = dt.datetime(2026, 6, 1, 12, 0, tzinfo=dt.timezone.utc)

_ONE_TASK = {
    "candidates": [{
        "type": "task", "title": "Ship the report", "summary": "Ship the report by Friday",
        "priority": "high", "due_date": "2026-06-05", "assignees": ["bob"],
        "source_message_ids": [1], "supporting_message_ids": [], "reasoning_summary": "explicit ask",
        "missing_fields": [],
        "confidence": {"item": 0.95, "context": 0.8, "assignee": 0.9, "priority": 0.7, "due_date": 0.8},
    }],
    "context_summary": "report", "context_confidence": 0.8,
}


def test_run_pipeline_emits_bot_notify(db):
    r = get_redis()
    r.delete(queue.NOTIFY_KEY)
    ext = 8200
    db.add(m.Assignee(display_name="Bob", telegram_username="bob", is_active=True))
    db.flush()
    msgs = [FetchedMessage(
        external_message_id=1, sender_external_id=1, sender_username="alice",
        sender_display_name="Alice", text="@bob ship the report by Friday, urgent",
        sent_at=BASE + dt.timedelta(minutes=1), raw={"id": 1},
    )]

    consumer.run_pipeline(
        db, FakeConnector({ext: msgs}), ext, m.SyncTriggerType.manual,
        llm_client=FakeLLMClient(_ONE_TASK),
    )

    cand = db.query(m.Candidate).one()
    notify = queue.dequeue_notify(timeout=2)
    assert notify == {"type": "bot.notify", "candidate_id": cand.id}
    assert r.llen(queue.NOTIFY_KEY) == 0
    r.delete(queue.NOTIFY_KEY)


def test_run_pipeline_no_notify_when_nothing_saved(db):
    """A re-sync that saves 0 messages skips extraction → emits no notify."""
    r = get_redis()
    r.delete(queue.NOTIFY_KEY)
    ext = 8201
    db.add(m.Assignee(display_name="Bob", telegram_username="bob", is_active=True))
    db.flush()
    msgs = [FetchedMessage(
        external_message_id=1, sender_external_id=1, sender_username="alice",
        sender_display_name="Alice", text="@bob ship the report by Friday, urgent",
        sent_at=BASE + dt.timedelta(minutes=1), raw={"id": 1},
    )]
    conn = FakeConnector({ext: msgs})
    consumer.run_pipeline(db, conn, ext, m.SyncTriggerType.manual, llm_client=FakeLLMClient(_ONE_TASK))
    queue.dequeue_notify(timeout=2)  # drain the first (legit) notify
    r.delete(queue.NOTIFY_KEY)

    consumer.run_pipeline(db, conn, ext, m.SyncTriggerType.scheduled, llm_client=FakeLLMClient(_ONE_TASK))
    assert r.llen(queue.NOTIFY_KEY) == 0  # nothing saved → no extraction → no notify
    r.delete(queue.NOTIFY_KEY)
```

Run and confirm the first test fails for the right reason (no notify emitted):
```
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest worker/tests/test_notify_emit.py -q
```
**Expected:** `test_run_pipeline_emits_bot_notify` fails on
`assert notify == {"type": "bot.notify", "candidate_id": cand.id}` because `notify` is `None`
(nothing emitted yet). Exit non-zero.

### Green — emit notify in `run_pipeline`

Edit `worker/src/aiwip_worker/consumer.py`. In `run_pipeline` (consumer.py:76-81), the gate
block currently is:
```python
    if run.status == SyncRunStatus.success and (run.messages_saved or 0) > 0:
        try:
            extract.extract_candidates(db, chat.id, client=llm_client)
        except Exception:  # noqa: BLE001 — extraction failure must not fail the sync job
            logger.exception("extraction failed chat=%s", chat_id)
        _mark_analyzed(db, chat.id)
```
Replace with (capture the created candidates, emit one notify each):
```python
    if run.status == SyncRunStatus.success and (run.messages_saved or 0) > 0:
        try:
            created = extract.extract_candidates(db, chat.id, client=llm_client)
            for cand in created:
                queue.enqueue_notify(cand.id)
        except Exception:  # noqa: BLE001 — extraction failure must not fail the sync job
            logger.exception("extraction failed chat=%s", chat_id)
        _mark_analyzed(db, chat.id)
```

> `queue` is already imported in consumer.py (`from aiwip_core import queue`, consumer.py:6),
> so no new import is needed. The notify is emitted **inside** the existing try/except so a
> Redis hiccup during notify cannot fail the (successful) sync job — consistent with the
> "extraction failure must not fail the sync job" rule already documented at consumer.py:79.

Run and confirm pass:
```
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest worker/tests/test_notify_emit.py -q
```
**Expected:** `2 passed`. Exit code 0.

### Commit (only if the user asks)
`feat: emit bot.notify per new candidate after extraction`

---

## Task 6.6 — Bot `ingest.py`: forward-only LPUSH + debounced enqueue (Red→Green)

**Goal:** the bot side of the contract. There is exactly **ONE** `bot/src/aiwip_bot/ingest.py`
with a single public capture entrypoint — `ingest_message` — that owns the buffer push,
debounce, and configure gate. `ingest.py` exposes:
- `record_from_update(update: dict) -> dict` — map a Bot API message update to the canonical
  buffer record shape `BotApiConnector` expects (the `FetchedMessage`-mirroring keys, see below).
- `ingest_message(external_chat_id, record, *, debounce_seconds, is_configured=...) -> bool` —
  RPUSH the record to `aiwip:botbuf:{chat}` and, **debounced**, enqueue exactly one
  `telegram.sync` job per quiet window. Returns `True` iff this call enqueued a job (so
  callers/tests can assert coalescing).

> **Single buffer writer (resolves the cross-phase ingest collision).** Phase 5 must NOT define
> a second buffer writer (`handle_inbound_message` / a local `buffer_key` / a raw RPUSH). The
> only code that writes `aiwip:botbuf:{chat}` is `queue.push_botbuf` (core, Task 6.1), called by
> `ingest_message` after `record_from_update` maps the Telegram update. Phase 5 contributes ONLY
> the gate predicate (`state.is_chat_configured`) and onboarding handoff. If Phase 5 already
> shipped an `ingest.py` body, Phase 6 lands as an **additive edit** to that file (add
> `record_from_update` + `ingest_message`), not a recreate — the two contributions live in one
> file with one public capture entrypoint.
>
> **Canonical buffer record shape** (the only shape ever pushed; `BotApiConnector` requires it):
> keys `external_message_id: int`, `sender_external_id: int|None`, `sender_username: str|None`,
> `sender_display_name: str|None`, `text: str|None`, `sent_at: ISO-8601 str`, `raw: dict`,
> `message_type: str = "text"`, `attachments: list`. The raw `{chat_id, message_id, from_user_id,
> text, date}` inbound dict must NOT be pushed — `record_from_update` maps it into this shape.

Debounce mechanism (design §4.2: "≤1 in-flight extract job per chat"): a Redis key
`aiwip:botlock:{chat}` set with `SET key 1 NX EX <debounce_seconds>`. The first message in a
window wins the lock and enqueues the job; subsequent messages within the window only push to
the buffer (the single job will drain *all* buffered messages when it runs). This yields
**N messages → 1 job** per window.

> **Configure-before-capture gate (design §7):** Phase 5 owns the actual gate, exposed as the
> canonical predicate **`state.is_chat_configured(chat_id) -> bool`** (backed by the Redis key
> `aiwip:botcfg:{chat}`). Phase 6's `ingest.py` accepts an injectable `is_configured` callable so
> capture is skipped for unconfigured chats; its default delegates to `state.is_chat_configured`,
> and the test injects its own. This keeps Phase 6 surgical and avoids reaching into Phase-5
> internals. (There is **no** `onboarding.is_configured` — the single canonical name is
> `state.is_chat_configured`.)

### Red — write the failing test

Create `bot/tests/test_ingest.py`:

```python
"""Phase 6 — bot ingest: forward-only buffer push + debounced enqueue."""
import datetime as dt

from aiwip_core import queue
from aiwip_core.redis_client import get_redis
from aiwip_bot import ingest

BOTLOCK_PREFIX = "aiwip:botlock:"


def _update(chat_id: int, mid: int, text: str = "hi") -> dict:
    return {
        "message": {
            "message_id": mid,
            "date": 1717243200,  # 2024-06-01T12:00:00Z epoch
            "chat": {"id": chat_id},
            "from": {"id": 500 + mid, "username": "u", "first_name": "U"},
            "text": text,
        }
    }


def test_record_from_update_maps_fields():
    rec = ingest.record_from_update(_update(7777, 9, "ship it"))
    assert rec["external_message_id"] == 9
    assert rec["sender_external_id"] == 509
    assert rec["sender_username"] == "u"
    assert rec["sender_display_name"] == "U"
    assert rec["text"] == "ship it"
    assert rec["message_type"] == "text"
    # sent_at must be an ISO string BotApiConnector can parse
    dt.datetime.fromisoformat(rec["sent_at"])


def test_debounce_coalesces_n_messages_to_one_job(monkeypatch):
    chat = 7800
    r = get_redis()
    r.delete(queue.botbuf_key(chat))
    r.delete(f"{BOTLOCK_PREFIX}{chat}")
    r.delete(queue.JOBS_KEY)

    enqueued = []
    monkeypatch.setattr("aiwip_core.queue.enqueue_sync", lambda *a, **k: enqueued.append((a, k)))

    for mid in (1, 2, 3):
        ingest.ingest_message(chat, ingest.record_from_update(_update(chat, mid)),
                              debounce_seconds=60, is_configured=lambda c: True)

    assert queue.botbuf_len(chat) == 3      # all three buffered
    assert len(enqueued) == 1               # exactly one job for the burst
    assert enqueued[0][0][0] == chat        # enqueue_sync(chat, ...)
    r.delete(queue.botbuf_key(chat))
    r.delete(f"{BOTLOCK_PREFIX}{chat}")


def test_unconfigured_chat_captures_nothing(monkeypatch):
    chat = 7801
    r = get_redis()
    r.delete(queue.botbuf_key(chat))
    r.delete(f"{BOTLOCK_PREFIX}{chat}")
    enqueued = []
    monkeypatch.setattr("aiwip_core.queue.enqueue_sync", lambda *a, **k: enqueued.append(1))

    did = ingest.ingest_message(chat, ingest.record_from_update(_update(chat, 1)),
                                debounce_seconds=60, is_configured=lambda c: False)

    assert did is False
    assert queue.botbuf_len(chat) == 0   # not pushed
    assert enqueued == []                 # not enqueued
    r.delete(queue.botbuf_key(chat))
```

Run and confirm failure (module missing):
```
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest bot/tests/test_ingest.py -q
```
**Expected:** `ModuleNotFoundError: No module named 'aiwip_bot.ingest'`. Exit non-zero.

### Green — create `ingest.py`

Create `bot/src/aiwip_bot/ingest.py`:

```python
"""Forward-only ingestion: inbound Bot API message → Redis buffer → debounced sync job.

The bot RPUSHes each post-join message to aiwip:botbuf:{chat} (drained later by the worker's
BotApiConnector). To avoid one LLM extraction per chat line, enqueue is debounced via a Redis
lock aiwip:botlock:{chat}: the first message in a quiet window enqueues a single telegram.sync
job; everything else in the window only buffers. The one job drains the whole buffer (design §4.2).
"""
from __future__ import annotations

import datetime as dt

from aiwip_core import queue
from aiwip_core.redis_client import get_redis

BOTLOCK_PREFIX = "aiwip:botlock:"


def _botlock_key(external_chat_id: int) -> str:
    return f"{BOTLOCK_PREFIX}{external_chat_id}"


def record_from_update(update: dict) -> dict:
    """Map a Bot API message update to the buffer record BotApiConnector consumes."""
    msg = update["message"]
    frm = msg.get("from") or {}
    sent_at = dt.datetime.fromtimestamp(msg["date"], tz=dt.timezone.utc)
    return {
        "external_message_id": msg["message_id"],
        "sender_external_id": frm.get("id"),
        "sender_username": frm.get("username"),
        "sender_display_name": frm.get("first_name"),
        "text": msg.get("text"),
        "sent_at": sent_at.isoformat(),
        "raw": {"id": msg["message_id"], "reply_to": (msg.get("reply_to_message") or {}).get("message_id")},
        "message_type": "text",
        "attachments": [],
    }


def _default_is_configured(external_chat_id: int) -> bool:
    """Configure-before-capture gate (design §7). Phase 5 owns the real check; default to its API.

    Canonical predicate is `state.is_chat_configured` (Phase 5, backed by aiwip:botcfg:{chat}).
    """
    from . import state

    return state.is_chat_configured(external_chat_id)


def ingest_message(
    external_chat_id: int,
    record: dict,
    *,
    debounce_seconds: int,
    is_configured=_default_is_configured,
) -> bool:
    """Buffer one inbound message and, debounced, enqueue one sync job. Returns True iff a job was enqueued."""
    if not is_configured(external_chat_id):
        return False  # configure-before-capture: drop pre-config chatter
    queue.push_botbuf(external_chat_id, record)
    won_lock = get_redis().set(_botlock_key(external_chat_id), "1", nx=True, ex=debounce_seconds)
    if won_lock:
        queue.enqueue_sync(external_chat_id, trigger="manual")
        return True
    return False
```

> **`message_type`/attachments:** MVP captures text only via the Bot API path (design §3:
> "No OCR / voice transcription improvement — Bot API media is metadata-only, same as today").
> Non-text updates can be mapped in a fast-follow; keeping this text-only is the surgical MVP.
> `state.is_chat_configured` is the canonical Phase-5 gate surface (Redis key
> `aiwip:botcfg:{chat}`); `_default_is_configured` calls it directly — no reconciliation needed.

Run and confirm pass:
```
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest bot/tests/test_ingest.py -q
```
**Expected:** `3 passed`. Exit code 0.

### Commit (only if the user asks)
`feat: bot forward-only ingest with debounced enqueue`

---

## Task 6.7 — Alembic migration: add `ConnectorType` value `telegram_bot` (Red→Green)

**Goal:** add the enum value `'telegram_bot'` to the model and a forward-only Alembic migration
that runs `ALTER TYPE connector_type ADD VALUE 'telegram_bot'` (design §8 / Decisions §16.2).
`ALTER TYPE ... ADD VALUE` cannot run inside a transaction block, so the migration uses
`op.execute` with autocommit.

### Red — write the failing test

Create `core/tests/test_connector_type_telegram_bot.py`:

```python
"""Phase 6 — ConnectorType gains telegram_bot."""
from aiwip_core.models import ConnectorType


def test_telegram_bot_member_exists():
    assert ConnectorType.telegram_bot.value == "telegram_bot"
```

Run and confirm failure:
```
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest core/tests/test_connector_type_telegram_bot.py -q
```
**Expected:** `AttributeError: telegram_bot` (no such enum member). Exit non-zero.

### Green — model + migration

1. Edit `core/src/aiwip_core/models.py` `ConnectorType` (models.py:51-56). Add the member as
   the **first active** value after `telegram`:
   ```python
   class ConnectorType(str, enum.Enum):
       telegram = "telegram"          # active (MVP) — Telethon, removed at Phase-6 cutover
       telegram_bot = "telegram_bot"  # active — Bot API forward-only capture
       slack = "slack"        # reserved/future
       email = "email"        # reserved/future
       whatsapp = "whatsapp"  # reserved/future
       discord = "discord"    # reserved/future
   ```

2. Create the migration `core/alembic/versions/c1d2e3f4a5b6_add_connector_type_telegram_bot.py`:
   ```python
   """add connector_type telegram_bot

   Revision ID: c1d2e3f4a5b6
   Revises: 2fe660361238
   Create Date: 2026-06-26 00:00:00.000000
   """
   from typing import Sequence, Union

   from alembic import op


   revision: str = 'c1d2e3f4a5b6'
   down_revision: Union[str, None] = '2fe660361238'
   branch_labels: Union[str, Sequence[str], None] = None
   depends_on: Union[str, Sequence[str], None] = None


   def upgrade() -> None:
       # ALTER TYPE ... ADD VALUE cannot run inside a transaction block; use autocommit.
       # IF NOT EXISTS makes the migration idempotent against the create_all() test schema.
       with op.get_context().autocommit_block():
           op.execute("ALTER TYPE connector_type ADD VALUE IF NOT EXISTS 'telegram_bot'")


   def downgrade() -> None:
       # Forward-only (Decisions §16.2): Postgres cannot DROP a value from an enum without a
       # type rebuild. Downgrade is intentionally a no-op.
       pass
   ```

   > Test schemas are built by `Base.metadata.create_all` (root `conftest.py:31`), which reads
   > the enum members directly from the model — so the new value is present in the test DB
   > without running the migration, and the unit test above passes on the model change alone.
   > The migration is for the real (migrated) database.

Run the enum test:
```
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest core/tests/test_connector_type_telegram_bot.py -q
```
**Expected:** `1 passed`. Exit code 0.

Verify the migration chains to a single head:
```
cd /Users/eduardshatalov/Documents/telegram-task-bot/core && python -m alembic heads
```
**Expected:** exactly one head printed: `c1d2e3f4a5b6 (head)`. Exit code 0.

Apply the migration against a real DB (requires local Postgres; the migration is the contract
for production):
```
cd /Users/eduardshatalov/Documents/telegram-task-bot/core && python -m alembic upgrade head
```
**Expected:** alembic logs `Running upgrade 2fe660361238 -> c1d2e3f4a5b6`. Exit code 0.

### Commit (only if the user asks)
`feat: add telegram_bot connector type + forward-only migration`

---

## Task 6.8 — `get_or_create_chat` resolves bot chats to `telegram_bot` (Red→Green)

**Goal:** `consumer.get_or_create_chat` (consumer.py:32-40) currently hard-codes
`ConnectorType.telegram` in both the lookup and the create. A buffer-sourced sync must resolve
(or create) the chat as `telegram_bot`, so the 6.4 factory picks `BotApiConnector` on the next
job. Add a `connector_type` parameter (default `telegram`, preserving current behavior).

### Red — write the failing test

Create `worker/tests/test_get_or_create_chat_bot.py`:

```python
"""Phase 6 — get_or_create_chat can resolve/create a telegram_bot chat."""
from aiwip_core import models as m
from aiwip_worker import consumer


def test_creates_bot_chat_with_bot_connector_type(db):
    chat = consumer.get_or_create_chat(db, 9100, connector_type=m.ConnectorType.telegram_bot)
    assert chat.connector_type == m.ConnectorType.telegram_bot


def test_default_remains_telegram(db):
    chat = consumer.get_or_create_chat(db, 9101)
    assert chat.connector_type == m.ConnectorType.telegram
```

Run and confirm failure (unexpected kwarg):
```
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest worker/tests/test_get_or_create_chat_bot.py -q
```
**Expected:** `TypeError: get_or_create_chat() got an unexpected keyword argument 'connector_type'`.
Exit non-zero.

### Green — parameterize the chat resolver

Edit `worker/src/aiwip_worker/consumer.py` `get_or_create_chat` (consumer.py:32-40). Replace:
```python
def get_or_create_chat(db: Session, chat_id: int) -> Chat:
    chat = db.execute(
        select(Chat).where(Chat.connector_type == ConnectorType.telegram, Chat.external_chat_id == chat_id)
    ).scalar_one_or_none()
    if chat is None:
        chat = Chat(connector_type=ConnectorType.telegram, external_chat_id=chat_id, title=f"chat {chat_id}")
        db.add(chat)
        db.commit()
    return chat
```
with:
```python
def get_or_create_chat(
    db: Session, chat_id: int, connector_type: ConnectorType = ConnectorType.telegram
) -> Chat:
    chat = db.execute(
        select(Chat).where(Chat.connector_type == connector_type, Chat.external_chat_id == chat_id)
    ).scalar_one_or_none()
    if chat is None:
        chat = Chat(connector_type=connector_type, external_chat_id=chat_id, title=f"chat {chat_id}")
        db.add(chat)
        db.commit()
    return chat
```

Run the new test plus the consumer/e2e regression suite (the default-arg call sites at
consumer.py:46, 73, and the `process_job` call added in 6.4 stay valid):
```
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest worker/tests/test_get_or_create_chat_bot.py worker/tests/test_consumer.py worker/tests/test_e2e.py -q
```
**Expected:** all pass. Exit code 0.

> The bot's `ingest.ingest_message` enqueues plain `telegram.sync` jobs (no connector type in
> the payload). For `process_job` (6.4) to pick `BotApiConnector`, the chat row must already be
> `telegram_bot`. Phase 5's onboarding creates the chat as `telegram_bot` when it is configured
> (configure-before-capture). This task gives onboarding the parameterized resolver it needs;
> the default keeps every existing telethon-sourced call unchanged. If Phase 5 has not yet
> wired `connector_type=telegram_bot` at chat creation, that is the one-line reconciliation noted
> in SELF-REVIEW.

### Commit (only if the user asks)
`feat: resolve bot-owned chats as telegram_bot connector type`

---

## Task 6.9 — Full real-time path integration test (Red→Green, end-to-end)

**Goal:** prove the whole forward-only loop end-to-end with no Telethon: bot `ingest_message`
→ buffer → `process_job` (factory picks `BotApiConnector`) → `run_sync` saves → gate fires →
candidate → `bot.notify`. This is the acceptance test for Phase 6's "capture → candidate in
seconds" deliverable. It uses a real DB and real Redis; it injects `FakeLLMClient` for
determinism and stubs the session factory to the test session.

### Red — write the failing test

Create `worker/tests/test_realtime_ingest_e2e.py`:

```python
"""Phase 6 — full forward-only path: bot ingest → buffer → process_job → candidate → notify."""
from aiwip_core import models as m
from aiwip_core import queue
from aiwip_core.redis_client import get_redis
from aiwip_worker import consumer
from aiwip_worker.llm.client import FakeLLMClient
from aiwip_bot import ingest

BOTLOCK_PREFIX = "aiwip:botlock:"

_ONE_TASK = {
    "candidates": [{
        "type": "task", "title": "Ship the report", "summary": "Ship the report by Friday",
        "priority": "high", "due_date": "2026-06-05", "assignees": ["bob"],
        "source_message_ids": [1], "supporting_message_ids": [], "reasoning_summary": "explicit ask",
        "missing_fields": [],
        "confidence": {"item": 0.95, "context": 0.8, "assignee": 0.9, "priority": 0.7, "due_date": 0.8},
    }],
    "context_summary": "report", "context_confidence": 0.8,
}


def _update(chat_id: int, mid: int, text: str) -> dict:
    return {"message": {"message_id": mid, "date": 1717243200 + mid,
                        "chat": {"id": chat_id}, "from": {"id": 700 + mid, "username": "alice", "first_name": "Alice"},
                        "text": text}}


def test_forward_only_capture_to_candidate(db):
    ext = 9500
    r = get_redis()
    for key in (queue.botbuf_key(ext), f"{BOTLOCK_PREFIX}{ext}", queue.JOBS_KEY, queue.NOTIFY_KEY):
        r.delete(key)

    # bob exists + the chat is a configured bot chat (Phase 5 would have created it)
    db.add(m.Assignee(display_name="Bob", telegram_username="bob", is_active=True))
    consumer.get_or_create_chat(db, ext, connector_type=m.ConnectorType.telegram_bot)
    db.flush()

    # 1. two inbound messages arrive (forward-only) → buffered, ONE job enqueued (debounce)
    ingest.ingest_message(ext, ingest.record_from_update(_update(ext, 1, "@bob ship the report by Friday, urgent")),
                          debounce_seconds=60, is_configured=lambda c: True)
    ingest.ingest_message(ext, ingest.record_from_update(_update(ext, 2, "thanks!")),
                          debounce_seconds=60, is_configured=lambda c: True)
    assert queue.queue_length() == 1
    assert queue.botbuf_len(ext) == 2

    # 2. the worker drains the job (factory → BotApiConnector), with the test session + fake LLM
    job = queue.dequeue(timeout=2)
    consumer.process_job(job, session_factory=lambda: _SessionCtx(db), llm_client=FakeLLMClient(_ONE_TASK))

    # 3. messages persisted, gate fired, candidate created, notify emitted
    chat = db.query(m.Chat).filter_by(external_chat_id=ext, connector_type=m.ConnectorType.telegram_bot).one()
    assert db.query(m.Message).filter_by(chat_id=chat.id).count() == 2
    cand = db.query(m.Candidate).one()
    assert queue.dequeue_notify(timeout=2) == {"type": "bot.notify", "candidate_id": cand.id}
    assert queue.botbuf_len(ext) == 0  # buffer fully drained

    for key in (queue.botbuf_key(ext), f"{BOTLOCK_PREFIX}{ext}", queue.JOBS_KEY, queue.NOTIFY_KEY):
        r.delete(key)


class _SessionCtx:
    """Adapt the savepoint-isolated test session to process_job's `with sf() as db` contract."""
    def __init__(self, db):
        self._db = db
    def __enter__(self):
        return self._db
    def __exit__(self, *exc):
        return False
```

Run and confirm failure for the right reason. Before 6.4–6.8 are in place this fails on the
factory/notify/chat-type; after 6.1–6.8 it should be the **only** integration gap to close. If
6.1–6.8 are all green, this test should already pass — run it to confirm the wiring:
```
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest worker/tests/test_realtime_ingest_e2e.py -q
```
**Expected once 6.1–6.8 are green:** `1 passed`. Exit code 0. If it fails, the failing
assertion names the exact unwired step (job count / candidate / notify / buffer drain) — fix
that step, do not patch the test.

### Green
No new production code is expected beyond 6.1–6.8; this task **verifies integration**. If a gap
surfaces, the smallest root-cause fix goes in the already-touched module (per CLAUDE.md §3.4).

### Commit (only if the user asks)
`test: end-to-end forward-only capture to candidate + notify`

---

## Task 6.10 — Remove the 6h scheduler (Red→Green, single-writer cutover step 1)

**Goal:** Decisions §16.1 — the system becomes bot-only; the periodic scheduler is gone.
Remove `enqueue_scheduled_syncs` and its main-loop trigger so nothing re-syncs Telethon chats
on a timer.

### Red — write the failing (removal) test

Create `worker/tests/test_scheduler_removed.py`:

```python
"""Phase 6 cutover — the 6h scheduler is removed (bot is the single writer, Decisions §16.1)."""
from aiwip_worker import consumer, main


def test_enqueue_scheduled_syncs_is_gone():
    assert not hasattr(consumer, "enqueue_scheduled_syncs")


def test_main_does_not_reference_scheduled_sync():
    import inspect
    src = inspect.getsource(main.run)
    assert "enqueue_scheduled_syncs" not in src
    assert "sync_interval_seconds" not in src
```

Run and confirm failure (both symbols still present):
```
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest worker/tests/test_scheduler_removed.py -q
```
**Expected:** both tests fail (`enqueue_scheduled_syncs` exists; `main.run` still references it).
Exit non-zero.

### Green — delete the scheduler

1. Edit `worker/src/aiwip_worker/consumer.py` — delete `enqueue_scheduled_syncs`
   (consumer.py:116-120):
   ```python
   def enqueue_scheduled_syncs(db: Session) -> int:
       chats = db.execute(select(Chat).where(Chat.is_active.is_(True))).scalars().all()
       for chat in chats:
           queue.enqueue_sync(chat.external_chat_id, trigger="scheduled")
       return len(chats)
   ```
   Remove that entire function.

2. Edit `worker/src/aiwip_worker/main.py` `run()` (main.py:30-58). Remove the scheduler:
   - delete the `from aiwip_core.db import get_sessionmaker` import (main.py:32) — only the
     scheduler used it;
   - change the startup log (main.py:36-38) from
     `"worker starting: queue consumer + scheduler (every %ss)", settings.sync_interval_seconds`
     to `"worker starting: queue consumer"` (drop the `settings.sync_interval_seconds` arg);
   - delete `last_schedule = time.monotonic()` (main.py:40);
   - delete the entire `if now - last_schedule >= settings.sync_interval_seconds:` block
     (main.py:51-58).

   The resulting `run()` body is:
   ```python
   def run() -> None:
       """Main loop: drain the job queue, with a periodic heartbeat."""
       from . import consumer

       logger.info("worker starting: queue consumer")
       last_heartbeat = 0.0
       while True:
           try:
               consumer.consume_once(timeout=5)
           except Exception:  # noqa: BLE001 — a bad job must not kill the worker
               logger.exception("job processing error")

           now = time.monotonic()
           if now - last_heartbeat >= settings.worker_heartbeat_seconds:
               run_once()
               last_heartbeat = now
   ```

3. Update the consumer test that exercised the scheduler. Delete
   `test_enqueue_scheduled_syncs_active_only` from `worker/tests/test_consumer.py`
   (test_consumer.py:89-98) — it tests removed behavior. (Also drop the now-unused `monkeypatch`
   in that test's signature by deleting the whole function.)

Run the removal test plus the consumer suite:
```
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest worker/tests/test_scheduler_removed.py worker/tests/test_consumer.py -q
```
**Expected:** all pass (scheduler test green; consumer suite green minus the deleted test).
Exit code 0.

### Commit (only if the user asks)
`chore: remove the 6h scheduler (bot is single writer)`

---

## Task 6.11 — Remove the Telethon connector (Red→Green, single-writer cutover step 2)

**Goal:** Decisions §16.1 — delete the Telethon connector module, its import in the consumer,
and the `telethon` dependency. The bot is the sole writer. The factory (6.4) must now reject
`telegram` (no transport) so a stray legacy `telegram` chat cannot silently re-acquire a writer.

### Red — write the failing (removal) test

Create `worker/tests/test_telethon_removed.py`:

```python
"""Phase 6 cutover — Telethon is gone; only the bot writes (Decisions §16.1)."""
import importlib

import pytest


def test_telegram_connector_module_is_removed():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("aiwip_worker.connectors.telegram")


def test_factory_rejects_legacy_telegram_after_cutover():
    from aiwip_worker import consumer
    with pytest.raises(ValueError):
        consumer.build_connector("telegram")
```

Run and confirm failure (module still importable; factory still accepts `telegram`):
```
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest worker/tests/test_telethon_removed.py -q
```
**Expected:** both tests fail. Exit non-zero.

### Green — delete Telethon

1. Delete the connector file:
   ```
   rm /Users/eduardshatalov/Documents/telegram-task-bot/worker/src/aiwip_worker/connectors/telegram.py
   ```

2. Edit `worker/src/aiwip_worker/consumer.py`:
   - delete the import `from .connectors.telegram import TelegramConnector` (consumer.py:22);
   - in `build_connector` (added in 6.4) remove the `telegram` branch so only `telegram_bot`
     is served. The function becomes:
     ```python
     def build_connector(connector_type: str) -> Connector:
         """Pick the transport for a chat. Bot-only after the Phase-6 cutover (Decisions §16.1)."""
         if connector_type == "telegram_bot":
             return BotApiConnector()
         raise ValueError(f"no connector for connector_type={connector_type!r}")
     ```

3. Update the factory test from 6.4 (`worker/tests/test_connector_factory.py`): delete
   `test_factory_returns_telethon_for_telegram` (it referenced `consumer.TelegramConnector`,
   now gone) and change `test_factory_rejects_unknown_type` to assert `telegram` is rejected:
   ```python
   def test_factory_rejects_legacy_and_unknown_types():
       import pytest
       for bad in ("telegram", "slack"):
           with pytest.raises(ValueError):
               consumer.build_connector(bad)
   ```
   (The `test_factory_returns_bot_connector_for_telegram_bot` test from 6.4 stays.)

4. Remove the `telethon>=1.36` dependency from `worker/pyproject.toml` `dependencies`
   (the `"telethon>=1.36",` line). Leave `aiwip-core` and `openai` in place.

5. Delete the now-orphaned login helper if present:
   ```
   rm -f /Users/eduardshatalov/Documents/telegram-task-bot/worker/scripts/telegram_login.py
   ```
   (Check first: `ls /Users/eduardshatalov/Documents/telegram-task-bot/worker/scripts/ 2>/dev/null`.
   Only remove `telegram_login.py`; leave any other script untouched.)

Run the removal test, the factory test, and the full worker suite:
```
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest worker/tests/test_telethon_removed.py worker/tests/test_connector_factory.py worker/tests -q
```
**Expected:** all pass. Exit code 0.

### Commit (only if the user asks)
`chore: remove Telethon connector and dependency (bot-only ingestion)`

---

## Task 6.12 — Full-suite green gate after cutover (verification, no code change)

**Goal:** Iron Law §3.5 — fresh, complete evidence that the whole repo suite is green after the
Telethon removal (design §12 "the existing ~94-test suite must stay green throughout").

Run the entire suite from the repo root (local Postgres + Redis up):
```
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest -q
```
**Expected:** all tests pass, `0 failed`, exit code 0. Read the full summary line; count the
collected tests — it must be the prior baseline (~94–96) **minus** the two removed tests
(`test_enqueue_scheduled_syncs_active_only`, the telethon factory test) **plus** the Phase-6
tests added in 6.1–6.11. No test should be collected from a `connectors/telegram.py` import.

If any test fails, do **not** claim completion — read the failure, trace it to the cutover edit,
and apply the smallest root-cause fix (CLAUDE.md §3.4).

Container parity check (stale-image gotcha, design §1 ops note) — rebuild then boot the worker
and confirm it starts without the scheduler/Telethon:
```
cd /Users/eduardshatalov/Documents/telegram-task-bot && docker compose build worker && docker compose up -d worker && docker compose logs --tail=20 worker
```
**Expected:** the worker log shows `worker starting: queue consumer` (no scheduler line) and a
heartbeat; no `ModuleNotFoundError: telethon` and no import error for `connectors.telegram`.

### Commit (only if the user asks)
No code change — verification only. (If the user wants a record, `chore: phase-6 cutover verified`.)

---

## SELF-REVIEW checklist

**Spec coverage (design §4.2, §6.3, §8, §16.1, §16.2):**
- [x] `BotApiConnector` implements the `Connector` Protocol by draining `aiwip:botbuf:{chat}`
      ascending — Task 6.2 (design §4.2).
- [x] `run_sync` is unchanged; dedup invariant guarded — Task 6.3 (design §4.1 "one persist path").
- [x] `messages_saved>0` extraction gate unchanged; notify only fires when candidates are created
      — Tasks 6.5 + 6.9 (design §1 row "Extraction gate", §6.2).
- [x] Bot `ingest.py` LPUSHes inbound messages forward-only and debounces N→1 job — Task 6.6
      (design §4.2, §6.3 "debounce coalesces a burst into one extraction job").
- [x] `consumer._build_connector` is now a factory on `Chat.connector_type` — Task 6.4 (design §4.2).
- [x] Worker emits `bot.notify {candidate_id}` — Task 6.5 (design §4.2 data-flow, §10 main.py
      "consume bot.notify").
- [x] Configure-before-capture gate respected (unconfigured chat captures nothing) — Task 6.6
      (design §7).
- [x] Alembic forward-only `ALTER TYPE … ADD VALUE 'telegram_bot'` — Task 6.7 (design §8,
      Decisions §16.2).
- [x] Telethon connector removed + 6h scheduler removed; single writer — Tasks 6.10, 6.11
      (Decisions §16.1, design §14 Phase 6).
- [x] Suite stays green after removal — Task 6.12 (design §12).
- [x] RED tests demanded by the brief all present: buffer drained ascending (6.2), run_sync
      dedup holds (6.3), messages_saved>0 gate fires (6.5/6.9), debounce coalesces N→1 (6.6),
      suite green after Telethon removal (6.12).

**Zero placeholders:** no "TBD/TODO/add validation/handle edge cases/similar to Task N/etc.".
Every code block is complete and copy-pasteable; every verify step has an exact command and
expected output + exit code. (Confirmed by re-reading each task.)

**Type / name consistency with other phases:**
- `ConnectorType.telegram_bot` value `"telegram_bot"` matches the design §8 / §16.2 token and
  is the same string the 6.4 factory and 6.6 ingest path key on.
- Redis keys match the design §8 table exactly: `aiwip:botbuf:{chat}` (buffer),
  `aiwip:botlock:{chat}` (debounce). The notify key `aiwip:bot:notify` is the worker→bot list
  referenced by design §10 (`main.py` "consume bot.notify"); it is introduced here as
  `queue.NOTIFY_KEY` because no earlier phase defined it.
- `bot.notify` payload shape `{"type":"bot.notify","candidate_id":int}` is the contract the
  Phase-4 confirm-UX consumer (`bot/.../main.py`) reads; `candidate_id` is the `Candidate.id`
  primary key.
- `FetchedMessage` field names/types in the buffer record (6.2/6.6) match `connectors/base.py`
  exactly (`external_message_id`, `sender_external_id`, `sender_username`,
  `sender_display_name`, `text`, `sent_at`, `raw`, `message_type`, `attachments`).
- `queue.enqueue_sync(chat, trigger="manual")` (6.6) pushes the existing
  `type="telegram.sync"` job that `process_job` (6.4) matches — the job type string is reused
  verbatim, not renamed (renaming would break `process_job`'s guard at consumer.py:90).

**Dependency notes (cross-phase reconciliation — read before starting):**
1. **Phase 5 (onboarding) owns `onboarding.is_configured(external_chat_id) -> bool` and chat
   creation as `telegram_bot`.** Task 6.6's `ingest._default_is_configured` and Task 6.8's
   parameterized `get_or_create_chat(..., connector_type=telegram_bot)` assume those exist. If
   Phase 5 named the predicate differently or creates the chat with a different connector type,
   reconcile at exactly two lines: `ingest._default_is_configured` (import/call name) and the
   `connector_type=` passed by onboarding at chat creation. The tests inject their own
   `is_configured`, so 6.6 is green regardless; the integration test 6.9 seeds the bot chat
   explicitly.
2. **Phase 3 (bot scaffold) created `bot/src/aiwip_bot/__init__.py`, `bot/pyproject.toml`
   (depending on `aiwip-core`), and `bot/tests/`.** Task 6.6 adds `bot/src/aiwip_bot/ingest.py`
   into that package and `bot/tests/test_ingest.py`. If `bot/tests` is not yet on
   `pytest.ini` `testpaths`, add `bot/tests` there (one-line edit) so the new bot tests run
   with `python -m pytest`.
3. **Phase 1 added the per-field confidences + `unresolved_mentions` to `CandidateOut`** and the
   assignee ambiguity fix. Phase 6 does not touch those; `bot.notify` carries only
   `candidate_id`, and the bot fetches the full `CandidateOut` via the API (design §4.2,
   "bot renders DM card"). No coupling to Phase-1 schema fields here.
4. **Alembic head ordering:** this migration sets `down_revision='2fe660361238'`. If Phase 1's
   `unresolved_mentions` migration also revises `2fe660361238`, the two will fork the head — run
   `python -m alembic heads` after both land and, if two heads appear, chain Phase 6's migration
   onto Phase 1's by setting `down_revision` to Phase 1's revision id (Phase 1 ships first per
   design §14). This is the single ordering touch-point.
5. **`telethon` removal** drops the dependency from `worker/pyproject.toml` only. No other
   module imports `telethon` (verified: only `connectors/telegram.py` did). Re-run
   `grep -rn "telethon" worker/src` after 6.11 — expected: no matches.
