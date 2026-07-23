# Postmortem 001 — Live capture into new groups silently broken after the Phase-6 cutover

**Date of incident:** 2026-06-26 · **Severity:** High (silent data loss on the primary ingest path) ·
**Status:** Resolved same day, regression-tested

## Summary

For ~9 hours after the Phase-6 connector cutover, adding the bot to a **new** Telegram group
produced no Work Item candidates at all — messages were captured into the Redis buffer, but every
sync job for an unseen chat failed. Existing groups were unaffected, which made the failure easy
to miss. No user-visible error was produced anywhere: the pipeline just quietly did nothing.

## Timeline (times America/Montevideo, from commit history)

| Time | Event |
|---|---|
| 2026-06-26 12:09 | Phase-6 cutover lands ([`71ff06c`](../../commit/71ff06c)): Telethon removed, the bot becomes the **only** writer; `build_connector` now rejects the legacy `telegram` connector type |
| 12:09 → ~21:00 | Bug window: `process_job` still auto-creates unseen chats with `connector_type='telegram'` — every job for a new group raises inside the worker and is retried into the dead-letter `sync_runs` row |
| ~21:00 | Detected during dogfooding: a freshly-added group produced no candidate cards *(reconstructed — no alerting existed at the time, see Lessons)* |
| 21:29 | Fix + regression test land ([`5cc9cfa`](../../commit/5cc9cfa)); full suite 218 passed |

## Root cause

The cutover changed an invariant — "post-cutover, the bot is the only writer" — but one call site
kept the old default. `process_job` resolved unseen chats via `get_or_create_chat(db, chat_id)`,
whose default `connector_type` was the legacy `telegram`. `build_connector` (correctly) rejects
that type post-cutover, so the job failed **after** capture but **before** any candidate was
created. A classic seam bug: two modules each locally correct, the invariant broken between them.

## Why tests didn't catch it

The Phase-6.9 e2e (`test_forward_only_capture_to_candidate`) **pre-created the Chat row** in its
fixture — so the only code path never exercised was exactly the one that broke: job processing for
a chat that doesn't exist yet. The fixture encoded the happy assumption the bug lived in.

## Why detection took hours, not minutes

- No worker-error surfacing: failures landed in `sync_runs` rows nobody was watching.
- No alerting on the queue/worker at all; the worker's heartbeat only went to container logs.
- The failure was **partial** (old groups kept working), so day-to-day dogfooding looked normal.

## What was done

1. **Fix:** unseen chats are now created as `telegram_bot` — the only writer post-cutover
   ([`5cc9cfa`](../../commit/5cc9cfa), 2 lines in `worker/consumer.py`).
2. **Regression test that encodes the lesson:** a new e2e that deliberately does *not* pre-create
   the chat (`test_process_job_auto_creates_missing_chat_as_telegram_bot`).

## Prevention (follow-through)

- **Fixtures must not pre-build the state under test** — when a test pre-creates an entity, ask
  what happens on the path that creates it for real. Applied as a review heuristic since.
- **Worker liveness and queue depth are now externally observable** — `GET /health/worker`
  (503 on stale heartbeat) and `GET /metrics` (`aiwip_queue_depth`,
  `aiwip_worker_heartbeat_age_seconds`) shipped in PR [#3](../../pull/3), so a stuck/dying
  pipeline alerts an uptime monitor instead of waiting for a human to notice missing cards.
- Remaining gap (tracked): per-job failure metrics (`sync_runs` failure counter) so *partial*
  failures — this incident's shape — page too, not just total worker death.
