# Design Spec — Bot-First Telegram Capture & Confirm Layer

- **Date:** 2026-06-26
- **Project:** AI Work Intelligence Platform (`telegram-task-bot`, branch `build/v1`)
- **Status:** DRAFT — awaiting section-by-section approval (Iron Law §1.4: no implementation before approved design)
- **Author:** synthesized from a 15-agent design workflow (5 grounding readers → 3 architecture approaches → 3-judge panel → 4 adversarial critics), reconciled against the product owner's three explicit decisions.

> **Method note.** The design panel *unanimously* (3/3 judges) recommended a "minimal additive, interaction-only bot" that touches **zero** live code, because the brief weighted *safety-to-a-live-system* heavily. The product owner has instead chosen a **bot-first, real-time, forward-only** product. This spec follows the owner's direction, but folds in *every* critic finding the panel surfaced — including the two CRITICAL ones — as hard requirements. Where the owner's direction increases risk over "minimal," that is stated honestly in §13.

---

## 1. Context — the system as it exists today (verified facts)

All facts below were read out of the real codebase, not assumed.

| Concern | Reality today | Source |
|---|---|---|
| Ingestion | **Telethon USER session over MTProto** (not a Bot API bot). `TelegramConnector` builds `TelegramClient(StringSession(...), api_id, api_hash)`. No bot token, no webhook, no `getUpdates`, no live event handlers anywhere. | `worker/.../connectors/telegram.py:31-34` |
| Capture model | Incremental **history pull**: `fetch_messages` → `client.iter_messages(chat, min_id=after, limit=200, reverse=True)`. | `worker/.../connectors/telegram.py` |
| Trigger | (1) in-process scheduler every `sync_interval_seconds` (default **6h**) → `enqueue_scheduled_syncs`; (2) admin `POST /api/sync/run`. Jobs on Redis list `aiwip:jobs`, drained by `consume_once`→`process_job`→`run_pipeline` (sync→normalize→**gated** extract). | `worker/.../main.py`, `consumer.py:76` |
| Extraction gate | Runs only when `run.status==success AND messages_saved>0` — an unchanged window never re-extracts duplicates. | `consumer.py:76` |
| Pipeline | sync → normalize → context (20-msg window, `context.py` `DEFAULT_WINDOW=20`) → OpenAI extract → **Candidate** (never an auto WorkItem). | `worker/.../extract.py` |
| Human gate | `Candidate → (human approve) → WorkItem`. Approval is `POST /api/candidates/{id}/approve`, `require_admin`-gated, audited, 409 on re-approve, **the only** candidate→workitem path. | `candidates.py:142-156`, `core/.../promotion.py` |
| Per-field confidence | `Candidate` carries `task/context/assignee/priority/due_date` confidences + `missing_fields` (JSONB). Bands materialised as `status` by `extract._status_for` (`<0.60` dropped, `0.60–0.90` `needs_review`, `≥0.90` `new`). | `models.py:399-406`, `extract.py:49-54` |
| Assignee identity | `Assignee` already has `telegram_user_id` (BigInteger, **indexed** `ix_assignees_telegram_user_id`), `telegram_username`, `aliases` (JSONB), nullable `user_id` FK to `User`. | `models.py:363-379` |
| Resolver | `resolve_assignees` does **exact** normalized match (strip/`@`/lower) over `telegram_username`+`display_name`+`aliases` of active assignees. **No fuzzy, no `telegram_user_id` lookup, no ORDER BY.** | `resolver.py:16-36` |
| Auth | Cookie `aiwip_session` → opaque token → Redis `session:` lookup in `get_current_user`. `require_admin` checks only `role==admin`. Cookie is a **pure bearer token**; no per-request actor proof, no per-resource ownership check. `User.password_hash` is nullable ("NULL = no password login"). Cookie currently set **without `secure=True`**. | `auth.py:62-78`, `routers/auth.py:22` |
| Test baseline | ~94–96 test functions across 21 files, green. | repo |
| Ops pattern | 5 docker-compose services (postgres, redis, api, worker, web); the `worker` block (`env_file:.env`, `depends_on: api healthy`, resource limits, json-file logging) is a clean template for a 6th service. **Stale-image gotcha**: rebuild the image after source edits. | `docker-compose.yml`, `README.md` |

**Decisions/ratified constraints we must NOT contradict** (`docs/system-spec.md`, `docs/decisions.md`):
- AI never auto-creates a WorkItem. **Precision over recall** (a false task is worse than a missed weak signal).
- §12: never auto-create Assignees. §13: every action audited under the acting admin.
- D4: quiet-hours semantics in UTC. D8: 20-message context window. D9: one approved candidate → one work item.

---

## 2. Goal & the owner's three decisions

Build a **BotFather Bot API bot** as the **primary interface**, and migrate the operational loop onto it. Three decisions made by the owner, treated here as fixed inputs:

1. **D-OWNER-1 — Bot-first.** The Bot API bot (created via BotFather) is the main surface: capture, confirm, fix-assignee, settings, board destination, onboarding all happen in Telegram. The web app remains the **admin console** (big tables, roles, audit, rules, billing) — the bot is not expected to absorb those.
2. **D-OWNER-2 — Capture is bot-only and forward-only.** The bot reads **all** group messages going forward; **history is ignored**. No Telethon backfill required for bot-owned chats.
3. **D-OWNER-3 — Built with an agentic approach.** Implementation is orchestrated across specialized agents (in the spirit of the Landing Factory OS / CLAUDE.md §4), one production editor at a time, surgical changes (§14).

**Onboarding rule (owner):** when the bot is added to a group it **first asks for configuration** (which board / destination to log into) and only **after the chat is configured** does it begin capture. → encoded as the **configure-before-capture gate** (§7).

---

## 3. Non-goals (MVP)

- No history backfill (D-OWNER-2). **Telethon is removed entirely — the system becomes bot-only** (decided 2026-06-26). The Telethon connector and the 6h scheduler are deleted at the **Phase-6 cutover** (§14); there is no backfill module.
- No fuzzy / Levenshtein assignee matching. (Alias-capture is the precision-preserving substitute — §6.1.)
- No auto-approve, ever. "Auto" may at most **batch the approve prompt**; a human taps every approval.
- No OCR / voice transcription improvement (Bot API media is metadata-only, same as today).
- No public webhook/TLS ingress in MVP — use **long-poll `getUpdates`** (keeps the repo's no-inbound-port posture).
- No billing, no multi-workspace tenancy work (out of scope for this layer).

---

## 4. Chosen architecture & why (vs the rejected alternatives)

### 4.1 The decision

**Real-time, forward-only Bot API ingestion routed through the EXISTING `run_sync` persist path via a Redis staging buffer — i.e. the panel's "Hybrid `BotApiConnector`-behind-the-Protocol" design — with each bot-owned chat being a SINGLE writer (no Telethon on that chat).**

Why this exact shape:
- It reuses the **one** persistence + precision path (`run_sync` dedup on `(chat_id, external_message_id)`, `SyncState`, `SyncRun`, audit, and the `messages_saved>0` extraction gate) instead of adding a second writer to `Message`. This is the difference between the Hybrid approach (safe) and the naive Real-time approach (which the panel docked for a `Message`-table write race).
- **D-OWNER-2 removes the race entirely.** The Real-time approach's race was *Bot-API-writer vs Telethon-backfill on the same chat*. Forward-only + no backfill ⇒ bot-owned chats have no Telethon writer ⇒ single writer ⇒ no `IntegrityError` race. The owner's own simplification is what makes this safe.
- It delivers the **seconds-latency, bot-first capture** the owner wants, while every Iron Law holds structurally (capture still lands as a `Candidate`; `<0.60` still dropped; only a human tap promotes; actions audited under the real admin once linking lands — §6.4).

### 4.2 Data flow

```
Telegram group (bot is admin, privacy mode OFF)
        │  every message (forward-only)
        ▼
[bot service]  push raw record → Redis list  aiwip:botbuf:{chat}
        │  debounced: ≤1 in-flight extract job per chat (30–90s quiet window OR N-msg cap)
        ▼
enqueue EXISTING-shaped job → aiwip:jobs
        ▼
[worker]  process_job → run_sync(BotApiConnector drains buffer, ascending id)
        │  → existing dedup / SyncState / SyncRun / audit
        │  → messages_saved>0 ⇒ extraction gate fires
        ▼
normalize → context(20-msg) → OpenAI extract → Candidate (status by confidence band)
        ▼
worker emits  bot.notify {candidate_id}
        ▼
[bot service]  renders DM card → human taps Approve/Edit/Reject/Assign
        │  (bot authorizes the tapper FIRST — §6.4 — then calls existing endpoints)
        ▼
POST /approve (admin-gated, audited) → promotion.approve_candidate → WorkItem (inbox)
```

`BotApiConnector` implements the existing `Connector.fetch_messages(chat_external_id, after_message_id, limit)` contract (`connectors/base.py`) by draining `aiwip:botbuf:{chat}` in ascending id order into `FetchedMessage`s — so `run_sync` is **unchanged**. `consumer._build_connector` becomes a small factory keyed on `Chat.connector_type`; **a chat is owned by exactly one transport at a time** (mixing is disallowed → no double-ingest).

## 5. Alternatives considered (and why not)

| Approach | Verdict | Why not (for this owner's goal) |
|---|---|---|
| **Minimal additive (interaction-only)** — panel's unanimous pick | Rejected as the *target*, **adopted as Phase-1 de-risking step** (see §14) | Zero pipeline risk, but **does not capture** — review just moves to Telegram while a message still waits ≤6h to become a candidate. Contradicts D-OWNER-1/2. Its `/link` and confidence-policy ideas are grafted in. |
| **Naive Real-time (second direct writer to `Message`, bypassing `run_sync`)** | Rejected | Splits the persist path; races Telethon backfill (`run_sync` dedup is pre-select-then-insert, *not* `IntegrityError`-hardened — `sync.py:74-87`). We get the same latency from the Hybrid path **without** a second writer. |
| **Hybrid `BotApiConnector` via `run_sync` buffer** | **CHOSEN** | One persist path, per-chat transport, real-time, Iron-Laws intact. Made single-writer-safe by D-OWNER-2. |

---

## 6. The four hard problems — hardened decisions

### 6.1 Assignee resolution  *(contains a CRITICAL pre-existing bug fix)*

**Problem.** A free-text mention ("Саша", "@sasha", "Сашка") must map to the right `Assignee`, and ambiguity/unknown people must be visible and fixable — not silently guessed.

**The CRITICAL bug (independent of the bot).** `extract._link_assignees` (extract.py:190-200) creates a `CandidateAssignee` for **every** match returned by `resolve_assignees`, and the **first** (arbitrary, no `ORDER BY`) gets `is_primary=True`. Ambiguity does **not** downgrade status (`extract.py:157-161` only downgrades on *zero* match). So a 0.95-confidence task that matched two "Саша"s becomes `status=new` → a one-tap Approve card → the human approves a WorkItem assigned to the **wrong** person. This is precisely the precision violation the system exists to prevent.

**Decisions:**
- **(A) Fix at source.** When `resolve_assignees` returns `len>1` for a single mention, do **not** link all. Link none, append `"assignee"` to `missing_fields`, and downgrade `new → needs_review` (mirror the zero-match path). [highest-value, bot-independent]
- **(B) Give the bot a signal it can branch on.** Add to `CandidateOut` (schemas.py:72-84): `assignee_count`, `assignee_ambiguous: bool`, and `unresolved_mentions: string[]`. Today the bot literally cannot detect ambiguity — `CandidateOut` has **no** assignee fields at all.
- **(C) Preserve the original mention string.** Persist the unresolved mention text on the `Candidate` (new nullable JSONB `unresolved_mentions`), written in `_link_assignees`. Today the raw mention lives only in `ai_runs.output_payload`, so an `[Assign…]` picker cannot even say *"who is 'Сашка'?"*.
- **(D) Validate writes.** `_set_candidate_assignees` (candidates.py:49-58) must reject `assignee_ids` that don't exist or are `is_active=False` (422) — a stale bot button must not create a dangling assignment.
- **(E) Alias-capture (NOT fuzzy, NOT auto-create).** On a zero-match human pick, offer `[Add alias 'сашка' → Саша]` → `PATCH /api/assignees/{id}` appending to `Assignee.aliases`. `resolve_assignees` already reads aliases, so each manual fix becomes a permanent exact-match. Honors §12.
- **(F) Exact `telegram_user_id` pre-resolution.** Because the bot now reads messages (D-OWNER-2), it has the **real Telegram user-id** of `@`-mention entities and the sender. Match these against `Assignee.telegram_user_id` (already indexed) for a high-precision pre-fill the text resolver can't do. Still human-confirmed.

**Bot UX:** `len==1` → show it. `len>1` → `[Who?]` choose-buttons → `PATCH assignee_ids=[chosen]`. `len==0` → `[Assign…]` from `GET /api/assignees?active=true` titled with the preserved mention, plus optional `[Add alias]`.

### 6.2 Confirmation policy & anti-fatigue  *(IMPORTANT)*

**Problem.** In a busy group, per-message cards become spam; and any auto-create path would break the Iron Law.

**Decisions:**
- **Signals.** Drive the policy off `status`, `task_confidence`, `missing_fields`, **plus** `assignee/priority/due_date/context` confidence — all added to `CandidateOut` (decided 2026-06-26; columns already exist on the model).
- **Bands → action.** `status=new` AND `missing_fields` empty → low-friction one-tap **Approve/Reject/Assign** card (still a human tap; the bot must **never** call `/approve` itself). `status=needs_review` OR `missing_fields` non-empty → digest with `missing_fields` rendered as a badge. `<0.60` → stays dropped; the bot **never** resurrects it.
- **Debounce + digest are MANDATORY in MVP, not a fast-follow.** Coalesce each poll/extract cycle's new candidates per chat into **one** digest message (`N new: M ready · K need input`). The Redis watermark prevents *re-surfacing*; only debounce prevents *burst* spam.
- **No "Approve all".** A digest may batch the *prompt*; every approval is one tap → one `POST /approve`. This preserves per-item human judgment.
- **Quiet-hours default ON** (UTC, per D4), so a sync finishing at 03:00 holds to the next window.

### 6.3 Ingestion, BotFather privacy mode & forward-only rollout

**Decisions:**
- **Operational requirement:** BotFather **privacy mode = OFF** and the bot is a **group admin** — otherwise the Bot API delivers only commands/mentions/replies, not ordinary chatter, and capture silently under-collects. This is a deliberate, documented consent step (group members must accept an "always-listening" bot; ship a short data-policy note).
- **Forward-only** (D-OWNER-2): a Bot API bot cannot back-fill; it sees only post-join messages. That is accepted — history is ignored.
- **Single writer:** Telethon is removed entirely, so the bot is the sole writer to `Message` ⇒ no write race by construction. (Telethon stays live only until the Phase-6 cutover, purely as the candidate source for the confirm-loop phases — §14.)
- **Long-poll `getUpdates`** (no public webhook/TLS in MVP).
- **Cost control:** debounce coalesces a burst into one extraction job so `context.build_context` still sees a multi-message window (D8) and we don't fire an LLM call per chat line.

### 6.4 Auth, account-linking & authorization  *(CRITICAL — security-review gate)*

**Problem.** The cookie is a pure bearer token; `require_admin` only checks `role==admin` (auth.py:75-78). Nothing binds a Telegram tapper to a platform user. Telegram `callback_data` is attacker-controllable. So without new controls, the wrong Telegram user — including a non-platform group member — could approve/reassign by replaying a callback, and the audit log would read "bot".

**Decisions (all required before any approve/reject button ships):**
- **The bot authorizes the tapper itself, before calling the API.** On every callback: look up `callback.from_user.id` → `Assignee.telegram_user_id` (indexed) → `Assignee.user_id` → `User`; require `User.role==admin`. Everyone else gets *"ask an admin."*
- **Treat `callback_data` as untrusted.** Re-fetch the candidate by id and confirm it is still actionable server-side; never trust the action embedded in the button.
- **Per-user linking is IN the MVP** (not a fast-follow) — it is the only thing that makes the audit actor real (`candidates.py` logs `admin.id`). Flow:
  1. Admin clicks **"Link Telegram"** in the **web UI** (admin-initiated). API issues a **server-bound, single-use** one-time code under a NEW short-TTL Redis prefix `tglink:<code>` (≈5 min), **distinct** from `session:`.
  2. Admin DMs the bot `/link <code>`.
  3. Bot calls `POST /api/auth/telegram/redeem`. The endpoint binds the code to the **issuing** user server-side, writes `Assignee.telegram_user_id`, and ends by calling the **existing** `auth.create_session(user.id)` (no new auth scheme; `get_current_user`/`require_admin` keep working).
- **Redeem-endpoint hard requirements (this endpoint is a dedicated security review gate):**
  - **Never** accept a client-supplied `telegram_user_id` as proof of identity. The code proves the user; the bot supplies `telegram_user_id` only to *write* it after verification.
  - Single-use: atomic `GETDEL`/Lua compare-and-delete. Short TTL. `secrets.compare_digest` (constant-time).
  - **Rate-limit** per `telegram_user_id` and per IP. *(Grounding confirms NO rate-limiting exists anywhere in the repo — this is net-new and must be built/borrowed first.)*
  - Refuse the unlinked case (`Assignee.user_id IS NULL` → 400, "ask an admin to attach a User"). **Never auto-create a User; never grant admin.**
- **Harden the cookie path:** set `secure=True` on the session cookie (routers/auth.py:22); bot↔API over TLS.
- `require_admin` stays as the last line but is **necessary-not-sufficient**: the real decision ("is THIS telegram user an admin linked to THIS user?") lives in the bot + the link.

---

## 7. Onboarding flow — configure-before-capture gate

```
Bot added to group  → bot detects it is NOT yet configured for this chat
   → posts: "Чтобы я начал ловить задачи, выберите куда их складывать."
   → [Выбрать борду/назначение]  (board/destination picker)
   → (optional) [Кто здесь работает]  (map participants → assignees, fast-follow)
   → on config saved:  chat marked configured  →  capture begins (forward-only)
GATE:  chat NOT configured  ⇒  messages are NOT pushed to the extract buffer.
```
Per-chat config (destination, surface mode, debounce window, quiet hours) is stored in **Redis** for MVP (no schema change) — see §8.

---

## 8. Data-model delta (near-zero)

No new tables. Against the existing 19-table schema:

| Change | Type | Rationale |
|---|---|---|
| `Candidate.unresolved_mentions` (nullable JSONB) | **Alembic migration** (additive, nullable) | §6.1(C) — preserve mention text for `[Assign…]`. |
| `CandidateOut`: add `assignee_count`, `assignee_ambiguous`, `unresolved_mentions`, and the 4 per-field confidences (`assignee/priority/due_date/context`) | API schema only, no DDL | §6.1(B), §6.2 (decided) — give the bot a signal. |
| `ConnectorType` enum: add value `'telegram_bot'`; mark bot chats via existing `Chat.connector_type` | **Alembic migration** — forward-only `ALTER TYPE … ADD VALUE` (decided 2026-06-26) | Cleaner semantics than a config flag; one-way enum migration accepted. |
| Redis keys (no DDL): `aiwip:botbuf:{chat}` (buffer), `aiwip:botlock:{chat}` (debounce), `tglink:<code>` (link OTP), `botuser:`/`botcard:` (prefs/watermark), per-chat config | New prefixes | All ephemeral/operational state. |
| Bot token | `.env` secret; optional `ConnectorAccount` row with `credentials_ref` = env-var **name** (per D21, never the secret) | reuse existing table. |

Explicitly **not** changed: `Message`, `CandidateAssignee` (dedup keys, `is_primary` already exist).

---

## 9. API surface delta

**Reused verbatim:** `GET /api/candidates?status=…`, `GET /api/candidates/{id}`, `PATCH /api/candidates/{id}` (`UpdateCandidateRequest`), `POST /api/candidates/{id}/approve`, `POST /api/candidates/{id}/reject`, `GET /api/assignees?active=true`, `PATCH /api/assignees/{id}`, `POST /api/auth/login`, `auth.create_session/get_current_user/require_admin`.

**New / changed:**
- `POST /api/auth/telegram/redeem` — **security-critical** (§6.4).
- `POST /api/auth/telegram-link/start` (or a web-UI action) — issue the one-time code.
- `CandidateOut` additive fields (§8).
- `_set_candidate_assignees` validation (§6.1 D).
- `_link_assignees` ambiguity fix (§6.1 A).

---

## 10. New `bot/` service

Mirrors the `worker/` layout; 6th docker-compose service (`env_file:.env`, `depends_on: api+redis healthy`, resource limits, **no exposed port** — long-poll).

```
bot/
  Dockerfile
  src/aiwip_bot/
    main.py        # getUpdates long-poll loop; consume bot.notify; debounce timers
    ingest.py      # inbound msg → configure-gate check → LPUSH aiwip:botbuf:{chat} → debounced enqueue
    api_client.py  # httpx: login once, replay aiwip_session cookie; map 401 re-login, 409/404 conversationally
    authz.py       # per-callback tapper authorization (from_user.id → User → role)
    cards.py       # CandidateOut → message text + InlineKeyboardMarkup (truncation, badges)
    handlers.py    # callback handlers: approve/reject/edit/assign/who/settings
    onboarding.py  # configure-before-capture flow + per-chat config
    digest.py      # coalesce + quiet-hours + one-message digest
    state.py       # Redis: watermark, prefs, link codes, buffer, locks
    config.py      # TELEGRAM_BOT_TOKEN, BOT_API_BASE, BOT_ADMIN_EMAIL/PASSWORD, intervals, bands, quiet-hours
worker/.../connectors/bot_api.py   # BotApiConnector(fetch_messages) draining aiwip:botbuf:{chat}
worker/.../consumer.py             # _build_connector → factory on Chat.connector_type; new bot.notify emit
```

New config keys: `TELEGRAM_BOT_TOKEN`, `BOT_API_BASE=http://api:8000`, `BOT_ADMIN_EMAIL`, `BOT_ADMIN_PASSWORD`, `BOT_POLL_INTERVAL_SECONDS`, `BOT_DEBOUNCE_SECONDS`, `BOT_DIGEST_INTERVAL_SECONDS`, `AUTO_BAND=0.90`, `REVIEW_BAND=0.60`, quiet-hours window.

---

## 11. Bot ⇄ Web boundary

| In the bot (primary) | Stays in web (admin console) |
|---|---|
| Onboarding / configure-before-capture | Big candidate/work-item tables, bulk review |
| Capture (forward-only) | Roles & user management, **issuing link codes** |
| Confirm: approve / reject / edit (priority, due, assignee) | Audit log, evaluation/eval-cases, rules |
| Fix/disambiguate assignee, alias-capture | Analytics, billing (future) |
| Per-chat settings, quiet hours, digest mode | Anything destructive or high-blast-radius |

This honors D-OWNER-1 (bot-first) and the owner's original "80% bot / 20% web" framing.

---

## 12. Testing strategy (TDD — Iron Law §1.1)

- **Red-first** for each change. New `bot/tests/` mirrors `worker/tests/`.
- **Assignee bug (§6.1 A):** failing test — two active "Саша" assignees + a "Саша" mention ⇒ assert candidate becomes `needs_review` with **no** primary linked (today it links both, picks arbitrary primary, stays `new`).
- **Redeem endpoint (§6.4):** tests for single-use (second redeem 4xx), TTL expiry, rate-limit trip, rejection of client-supplied `telegram_user_id`, refusal of unlinked `Assignee`, no User auto-create.
- **Authz:** non-admin / unlinked tapper ⇒ denied; replayed `callback_data` for an already-approved candidate ⇒ no-op.
- **BotApiConnector:** buffer drained in ascending id order; `run_sync` dedup holds; `messages_saved>0` gate fires; debounce coalesces N messages → 1 job.
- **Confirmation:** burst of N candidates ⇒ exactly one digest; `<0.60` never surfaced; no "Approve all".
- **Baseline:** the existing ~94-test suite must stay green throughout (run against on-disk source; remember the stale-image gotcha for container checks).

---

## 13. Risks & mitigations (honest)

| Risk | Severity | Mitigation |
|---|---|---|
| New session-minting `/redeem` endpoint = auth-bypass surface | **High** | §6.4 hard requirements; dedicated security review **before** exposure; rate-limit built first. |
| Pre-existing silent mis-assignment | **High** | §6.1 (A)–(D) — fixed at source + made visible to the bot. |
| Privacy-mode misconfig silently under-collects | Medium | Runbook + onboarding check that warns if privacy mode appears on / bot not admin. |
| Per-message LLM cost > batched 200-msg pull | Medium | Debounce window + N-msg cap; tune `BOT_DEBOUNCE_SECONDS`. |
| "Always-listening" bot perceived as surveillance | Medium | Explicit team consent + data-policy note at onboarding. |
| Removing Telethon entirely loses history & any bot-downtime gap is unrecoverable | Medium (accepted) | Forward-only by decision; no backfill. Monitor bot liveness (MONITORING.md) so downtime gaps are detected. |
| Bot-admin credential in `.env` = full admin API access | Medium | Treat as top-tier secret; least-privilege; rotate. |
| Stale-image gotcha on the new service | Low | Document `docker compose build bot && up -d bot`. |

**Panel's caution, recorded:** all three judges preferred shipping the interaction-only confirm loop *first* (zero pipeline risk, reversible by removing a container) and treating real-time ingest as a deliberate, separately-consented step. §14 honors this by sequencing capture *after* a working confirm loop — without abandoning the bot-first target.

---

## 14. Agent-orchestrated implementation plan (per D-OWNER-3, CLAUDE.md §4)

One production editor per phase; never two agents on the same surface; QA gate mandatory; conventional commits only when asked. Each phase is `Red → verify → Green → verify → review`.

| Phase | Agent (role / model routing) | Scope (surgical) | Gate |
|---|---|---|---|
| **0. Approve spec** | — | This document, section by section | owner approval |
| **1. API/pipeline hardening** | backend-impl (Opus) | §6.1(A)(B)(C)(D) assignee fix + `CandidateOut` fields + `Candidate.unresolved_mentions` migration + tests | suite green; new assignee test red→green |
| **2. Auth & linking** | security-impl (Opus) — *isolated* | §6.4 redeem + start endpoints, rate-limit, single-use, `secure=True` | **security review** + tests |
| **3. Bot service scaffold** | bot-impl (Sonnet) | `bot/` package, 6th compose service, config, `api_client`, login+cookie replay | bot boots, `/health` via `GET /api/auth/me` |
| **4. Confirm UX** | bot-impl (Sonnet) | `cards`, `handlers`, `authz` per-callback, digest, quiet-hours; approve/reject/edit/assign | confirm loop works against seeded candidates |
| **5. Onboarding gate** | bot-impl (Sonnet) | `onboarding`, per-chat config, configure-before-capture gate | unconfigured chat captures nothing |
| **6. Real-time ingestion + Telethon cutover** | worker-impl (Opus) | `BotApiConnector` + buffer + debounce + `_build_connector` factory + `bot.notify`; **then remove the Telethon connector + 6h scheduler** (`ConnectorType` enum gains `'telegram_bot'`) | forward-only capture → candidate in seconds; old ingestion gone; suite green |
| **7. QA gate** | qa-critic (Opus) | Full suite, security re-check of redeem, privacy-mode runbook, end-to-end on one real group | **zero unresolved CRITICAL/REQUIRED** |

**Sequencing note (panel-informed):** Phases 3–5 deliver a usable confirm-in-Telegram loop *before* Phase 6 turns on real-time capture, so the riskiest change ships last, on top of a proven surface — while still reaching the bot-first target. **Telethon stays live as the candidate source through Phases 1–5 and is removed only in Phase 6 at cutover**, so the confirm loop is never starved of candidates (this reconciles Decisions §16.1 × §16.4).

---

## 15. MVP cut vs fast-follows

**MVP:** one configured work group; bot privacy OFF + admin; `getUpdates`; configure-before-capture; forward-only capture via `BotApiConnector`→`run_sync`; debounced one-job-per-burst; per-field assignee bug fixed; `needs_review`/missing-assignee surfaced as cards + high-confidence in a digest; approve/reject/edit/assign with **per-tapper authz** and **per-user `/link`**; quiet-hours on; no "Approve all"; Redis-only per-chat config (no schema beyond `unresolved_mentions`).

**Fast-follows:** alias-capture button; free-text title/summary edit (force-reply); `users.telegram_user_id` column to skip the `Assignee` bounce; per-chat settings UI; multi-group; optional one-shot Telethon backfill module; webhook hardening.

---

## 16. Decisions (resolved 2026-06-26)

1. **Telethon:** removed **entirely** — bot-only system. Deleted at the Phase-6 cutover (§14); no backfill.
2. **Transport marker:** add `ConnectorType` enum value **`'telegram_bot'`** (forward-only Alembic migration); bot chats marked via `Chat.connector_type`.
3. **Confidence routing:** **add** `assignee/priority/due_date/context` confidence to `CandidateOut` — richer per-field policy.
4. **Capture sequencing:** **confirm-loop first** (Phases 3–5), then real-time capture (Phase 6).
5. **Spec home:** kept in `telegram-task-bot/docs/specs/`; mirroring into the ClaudeBrain vault is optional and not required for the build.

**Cross-decision note:** #1 (remove Telethon) and #4 (confirm-loop first) reconcile by *timing* — Telethon remains the live candidate source through Phases 1–5 so the confirm loop has real candidates to act on, and is removed in **Phase 6** when bot capture replaces it. End state is bot-only.
