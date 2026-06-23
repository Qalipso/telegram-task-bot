# Stage 4 Report — Telethon Connector & Sync Engine

- **Date:** 2026-06-23 · **Branch:** `build/v1` · **Commits:** `ab50034`, `f72235d`, `30430cb`

## Goal
Read Telegram messages and persist them safely: connector, incremental sync, idempotent storage,
sync state/history, manual + scheduled triggers, error handling.

## Implemented
- **Connector layer** (`aiwip_worker/connectors/`): `Connector` protocol + `FetchedMessage`;
  `FakeConnector` (tests); **live `TelegramConnector`** (Telethon user session, `iter_messages(min_id)`).
- **Sync engine** (`aiwip_worker/sync.run_sync`): incremental fetch from `last_external_message_id`,
  **idempotent dedup** on `(chat_id, external_message_id)`, sync_state advances **only on success**,
  every run recorded in `sync_runs` (success/failed) with errors captured.
- **Redis job queue** (`aiwip_core/queue.py`): list-based enqueue/dequeue; `enqueue_sync`.
- **Worker consumer + scheduler** (`aiwip_worker/consumer.py`, `main.run`): BRPOP loop → `run_sync`;
  bounded retry (re-enqueue failed up to 3 attempts; the failed `sync_runs` row is the dead-letter
  record); periodic heartbeat; **6h scheduled-sync enqueue** for active chats.
- **Admin sync API** (`/api/sync`): `POST /run` (enqueues), `GET /status`, `GET /history` — all `require_admin`.
- **CLIs**: `scripts/telegram_login.py` (mint session → .env + list chats), `scripts/sync_once.py` (manual sync).

## Tests Run / Results
- `.venv/bin/python -m pytest` → **42 passed** vs real Postgres 16 + Redis 8.
- Stage 4 tests: connector/sync (saves, re-sync no-dups + only-new, failed records error + preserves
  state, run counts); queue roundtrip; consumer (sync_chat, requeue bounds, scheduled active-only);
  sync API (admin 202, assignee 403, unauth 401, status/history).
- **LIVE end-to-end verified** against chat `-1003769614853`:
  - first sync pulled **41 real messages**; re-sync **read=0/saved=0** (41 distinct, zero duplicates);
  - **queue → consumer → live sync**: enqueued a job, worker dequeued and ran the live sync, queue
    drained 1→0, recorded as `sync_run #3`.

## Bugs Found / Fixed
- A developer `.env` (docker hostnames `postgres`/`redis` + Telegram creds) broke env-coupled tests →
  centralized DB fixtures in a **root `conftest.py`** that forces localhost, so tests are independent
  of any `.env`.

## Remaining Risks / Notes
- **Retry/backoff is basic** (immediate bounded re-enqueue; no exponential backoff or separate DLQ
  queue). The persisted failed `sync_runs` is the dead-letter surface; D14 admin re-run = `retry` trigger.
  Harden in Stage 14 if needed.
- Scheduler is an in-process time check in the worker (fine for a single worker / 500 msg-day).
- `.env` uses docker hostnames; **host runs need localhost** DB/Redis (compose overrides them in-container).

## Decisions Made
- **build-D6:** Redis **list** queue (LPUSH/BRPOP); retry via consumer re-enqueue + failed `sync_runs`
  as the dead-letter record (no separate DLQ infra for MVP).
- Test infra centralized at repo-root `conftest.py`; `savepoint` isolation; forced localhost.

## Files Changed
`worker/src/aiwip_worker/{connectors/*,sync,consumer,main}.py`, `core/src/aiwip_core/{queue,config}.py`,
`api/src/aiwip_api/{main.py,routers/sync.py}`, `scripts/{telegram_login,sync_once}.py`,
`{conftest.py, api/tests/conftest.py}`, tests `worker/tests/{test_sync,test_queue,test_consumer}.py`,
`api/tests/test_sync_api.py`, `core/tests/test_config.py`.

## Next Recommended Stage
**Stage 5 — Message Normalization** (text → `normalized_content`; register attachments as placeholders;
update `processing_status`; unsupported files don't break sync). Then 6 (assignees) → 7 (context) →
**8 (OpenAI candidates — needs `OPENAI_API_KEY`)**.

## Proceed / Do Not Proceed
**PROCEED to Stage 5.** Sync path is complete and verified live end-to-end (42 tests + real-data sync +
queue-driven consumer). 41 real messages are in the DB ready for normalization.
