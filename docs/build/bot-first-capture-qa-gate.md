# Phase 7 — Bot-First Capture Layer · QA Gate (verification artifact)

> Gate per the design spec §14 and `docs/specs/impl-plan/phase-7-qa-gate.md`.
> **Agent:** qa-critic (adversarial audit) + orchestrator (verification & fixes).
> **Gate rule:** zero unresolved CRITICAL/REQUIRED.
> **Date:** 2026-06-27. **Branch:** `feat/bot-first-capture`.
> Every PASS below carries the command that produced it (Iron Law §1.3 — no claim without fresh evidence).

## Verdict: ✅ PASS

The bot-first Telegram capture & confirm layer (Phases 1–6) **plus** the in-Telegram admin panel
and outbound-webhook integration (the final feature layer) are verified working end-to-end. All
REQUIRED findings from the adversarial audit are resolved. One security item was escalated to the
product owner and resolved by explicit decision (see §5).

---

## 1. Test suite (canonical gate command)

Prerequisite: local Postgres (`aiwip_test`) + Redis on `localhost`. The live `worker`/`bot`
containers must be **stopped** during the run — they hold blocking `BRPOP` waiters on
`aiwip:jobs` / `aiwip:bot:notify` in Redis db0 and would otherwise drain the queue under the
queue-roundtrip tests (environmental, not a code defect — root-caused 2026-06-27).

```
docker stop aiwip-worker-1 aiwip-bot-1
./.venv/bin/python -m pytest -q          # 260 passed, 1 skipped — exit 0
./.venv/bin/python -m pytest --collect-only -q   # 261 tests collected
docker start aiwip-worker-1 aiwip-bot-1
```

- Result: **260 passed, 1 skipped** (the 1 skip is `test_api_client_live.py`, a CI-safe live-only test). Exit 0.
- Baseline at gate entry was 250 passed; +10 new tests were added during this gate (see §4).

## 2. Phase 1–6 contract surfaces — verified

| Surface | Check | Evidence | Status |
|---|---|---|---|
| `Candidate.unresolved_mentions` (JSONB) | column exists | `psql … information_schema.columns` → `unresolved_mentions \| jsonb` | ✅ |
| `ConnectorType.telegram_bot` enum | value present + used live | `pg_enum` on `connector_type` → `telegram_bot`, `telegram`; live `chats` has rows of both | ✅ |
| Alembic migrations | up/down/up clean on pristine DB | `alembic upgrade head → downgrade base → upgrade head` on scratch `aiwip_migtest`, exit 0 ×3; single head `415f2124f336` | ✅ |
| `POST /api/auth/telegram/redeem` single-use/refusal | invalid code refused, no leak | `curl` invalid code → `400 {"detail":"Invalid or expired link code"}` | ✅ |
| redeem rate-limit (`tglink:rl:tg:` / `tglink:rl:ip:`) | throttles | 12× hammer → `400 400 400 400 429 429 …`; Redis keys `tglink:rl:tg:555000`, `tglink:rl:ip:172.18.0.1` present | ✅ |
| Session cookie `Secure` | flag set | login `Set-Cookie: aiwip_session=…; HttpOnly; Max-Age=604800; Path=/; SameSite=lax; Secure` | ✅ |
| Bot `ApiClient` login / `me()` | 200 | bot logs: `POST /api/auth/login 200` → `bot logged in as admin@aiwip.local`; `GET /api/auth/me` → admin | ✅ |
| No "Approve all" | absent | grep: only docstrings in `cards.py`/`digest.py` documenting the *absence*; no button/handler | ✅ |
| Telethon removed (bot = single writer) | no active Telethon | grep `telethon`/`TelegramClient` in `worker/src core/src api/src` → none; no scheduler in `worker/src` | ✅ |
| `BotApiConnector` + `_build_connector` factory + `telegram_bot` path | present | `worker/.../connectors/bot_api.py:25 class BotApiConnector`; `consumer.py:30` connector dispatch | ✅ |

## 3. Authorization audit (qa-critic, read-only trace)

Every `admin:*` callback branch (`telegram_app.py`) and every `_admin_*` helper calls
`_admin_check` (→ `authz.authorize_tapper`, linked-admin-only) **before** returning data or
mutating — including the `_fetch_export` closure and `/setwebhook`. The `admin:integrations:help`
and unknown-command branches echo static text only. Card callbacks re-authorize per tap and treat
`callback_data` as untrusted. **No authorization hole found.**

## 4. Defects found & fixed (TDD: failing test → fix → green)

| # | Severity | Defect | Fix | Test |
|---|---|---|---|---|
| 1 | REQUIRED | `handle_approve` push side-effect not failure-isolated — `httpx.InvalidURL` is **not** an `httpx.HTTPError`, so a malformed stored webhook URL escaped `push_webhook` and propagated out of `handle_approve` *after* the candidate was already approved (user sees a failed action that actually succeeded). | Wrapped `push()` in `handle_approve` (`handlers.py`) + broadened `push_webhook` except to `Exception`. | `test_handle_approve_push_failure_does_not_fail_approval`, `test_push_webhook_invalid_url_returns_false` |
| 2 | MINOR | `admin:export` rendered untrusted work-item titles with `parse_mode="Markdown"` → a title containing `*`/`_`/`` ` `` makes Telegram 400 and the whole export silently fails. | Dropped `parse_mode`; export is plain text (same rationale as cards). | covered by manual + import verify; behavior matches plain-text card path |
| 3 | REQUIRED (coverage) | The aggregation math (`_dashboard_stats`, chat-detail counts, history `wi_map`) lived in `telegram_app.py`, which the host suite cannot import (no `aiogram` on host) → **zero coverage** on the only non-trivial logic. | Extracted pure `admin.dashboard_counters` / `admin.chat_task_stats` / `admin.build_wi_map` into the aiogram-free `admin.py`; `telegram_app` now calls them. | `test_dashboard_counters_math`, `test_chat_task_stats_filters_by_chat`, `test_build_wi_map_skips_null_source_candidate` |

## 5. Security decision — webhook SSRF (escalated & resolved)

`/setwebhook` previously accepted any `startswith("http")` string and the bot then POSTed work-item
JSON to it server-side — an SSRF primitive (e.g. `http://169.254.169.254/` cloud metadata). Escalated
to the product owner per `security-sensitive-changes`. **Decision (2026-06-27): https-only + block
loopback and link-local/cloud-metadata; allow private-LAN https** (to preserve self-hosted webhook
targets such as n8n). Implemented as `admin.validate_webhook_url` (resolves the host and checks every
mapped address) and wired into `/setwebhook`.

Live verification in the deployed bot image:
```
http://hooks.zapier.com/x   -> rejected (https-only)
https://169.254.169.254/…   -> rejected (link-local / metadata)
https://127.0.0.1/h         -> rejected (loopback)
https://hooks.zapier.com/abc-> allowed
```
**Residual risk (accepted by design):** RFC1918 private https targets (e.g. `https://api:8000`,
`192.168.x.x`) remain allowed — this is the deliberate trade-off of the chosen policy to support
self-hosted webhooks. Full private-range blocking (the stricter alternative) was considered and
declined by the owner.

## 6. Live end-to-end smoke (real `@TaskDefiner_bot`)

Stack: `postgres, redis, api, worker, bot, web` all healthy. Bot `id=8851058935` polling.
- Board: 5 work-items (3 inbox / 2 archived), 16 candidates (11 rejected / 5 approved). `GET /api/work-items/board` returns real extracted tasks with `source_chat_title` resolved via `enrich.py`.
- Pipeline verified: message → `run_sync` (run #29 success @17:09) → candidate → approve → work-item → board.
- Admin panel: bot logs show `admin:*` callbacks handled (dashboard/tasks/review/chats/integrations/history) against live data.

## 7. Process note

The admin panel + webhook integration were built in the working tree and were absent from the
original design spec (which still describes Telethon ingestion). They are in scope per the product
owner's explicit request ("кличка + спец-код → админ-панель; интеграции"). The design spec should be
updated to document the admin panel as a follow-up; this does not block the gate given the explicit
owner direction and the evidence above.
