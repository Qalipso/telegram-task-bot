# AI Work Intelligence Platform

Turns Telegram work discussions into reviewed **Work Items** through a human-in-the-loop AI pipeline:

```
Telegram → Sync → Normalize → Context → OpenAI candidates → Human review → WorkItem → Kanban board
```

Core principle: **the AI never creates final Work Items** — every candidate requires human approval.
Precision over recall in the review step: a false task is worse than a missed weak signal.

> **Operating the system:** see [`docs/RUNNING.md`](docs/RUNNING.md) for a full first-run and operations
> guide. **Integrating with other systems** (custom connectors, the AI provider, the REST API,
> data stores): see [`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md).
>
> Product/spec docs live in [`docs/`](docs/) (EN canonical + RU). Per-stage build reports are in
> [`docs/build/`](docs/build/). The authoritative spec is [`docs/system-spec.md`](docs/system-spec.md).

## Architecture

| Service | Tech | Role |
|---|---|---|
| `api` | FastAPI | REST: auth, candidate review, work items/board, assignees, sync control, audit, evaluation. `http://localhost:8000` |
| `web` | Next.js 16 / React 19 | Full operator UI (login, review queue, board, assignees, sync) + same-origin API proxy. `http://localhost:3000` |
| `worker` | Python + Telethon | Telegram sync, normalization, context builder, OpenAI extraction, job consumer + 6h scheduler |
| `core` | shared package | SQLAlchemy models (19 tables), config, db, redis, queue, logging, audit, promotion |
| `postgres` 16 / `redis` 7 | — | data + job queue/sessions |

The full ingestion pipeline (sync → normalize → context → OpenAI extract) runs inside the worker via
`consumer.run_pipeline()`. Extraction is **gated**: it runs only when a sync actually saved new
messages, so the periodic scheduled sync never re-extracts an unchanged window into duplicate candidates.

## Quick start (Docker)

```bash
cp .env.example .env          # fill secrets (see below)
docker compose up -d --build  # postgres, redis, api, worker, web
# api → http://localhost:8000 (GET /health, /health/ready)
# web → http://localhost:3000
```

Seed the first admin (after the stack is up):

```bash
docker compose exec -e ADMIN_EMAIL=you@example.com -e ADMIN_PASSWORD='change-me' \
  api python -m aiwip_api.seed
```

> ⚠️ **Stale-image gotcha.** The built `api` / `web` / `worker` images bundle source at build time.
> After editing source you **must rebuild** the affected service or the container keeps serving old
> code: `docker compose build <svc> && docker compose up -d <svc>`. This bites the `web` image in
> particular — rebuild it after any UI change. (Tests run against on-disk source, so they can pass
> while a running container is still stale.) See [`docs/RUNNING.md`](docs/RUNNING.md#troubleshooting).

Then connect Telegram and run a first sync — see [`docs/RUNNING.md`](docs/RUNNING.md#first-run).

## Web UI

The `web` service is a complete operator console (Next.js 16 / React 19) with five screens:

1. **Login** — email + password; on success the browser holds an httpOnly session cookie.
2. **Review queue** — candidate list with a status filter and a detail drawer showing the
   source-message text; edit, approve (→ WorkItem), or reject each candidate.
3. **Board** — a 9-column Kanban (`inbox → backlog → ready → in_progress → blocked → review → done →
   cancelled → archived`) with drag-and-drop plus a per-card status menu.
4. **Assignees** — admin management of the finite assignee list the AI resolver matches against.
5. **Sync** — dashboard of sync runs/state with a **Run sync now** button.

The browser never talks to the API directly. The UI calls a **same-origin Next.js proxy** at
`web/app/api/[...path]/route.ts` that forwards `/api/*` to `API_BASE` (Docker: `http://api:8000`;
local dev default: `http://localhost:8000`) and passes the `aiwip_session` httpOnly cookie through
in both directions, so authentication works without exposing the cookie to client JS.

**Serving the UI:**
- **Docker:** built into the `web` image — rebuild after UI edits: `docker compose build web && docker compose up -d web`.
- **Local dev (fast):** `cd web && npm install && npm run dev` → `http://localhost:3000`, proxying to
  the API at `http://localhost:8000`.

## Environment (`.env`)

| Var | Purpose |
|---|---|
| `APP_ENV` / `LOG_LEVEL` | runtime mode + log verbosity |
| `POSTGRES_USER/PASSWORD/DB` | Postgres container credentials |
| `DATABASE_URL` / `REDIS_URL` | service connection strings (compose overrides to in-network hosts) |
| `SECRET_KEY` | session signing — change for production |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | first-admin seed (passed to `python -m aiwip_api.seed`) |
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` / `TELEGRAM_PHONE` | from https://my.telegram.org |
| `TELEGRAM_SESSION` | Telethon session string — mint with `python scripts/telegram_login.py` (interactive) |
| `TELEGRAM_CHAT_ID` | target chat to sync |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | OpenAI (default `gpt-4o-mini`) |

Secrets go in `.env` only (gitignored) — never in source or chat. `TELEGRAM_SESSION` is equivalent to
a logged-in session; keep it secret. Full reference (incl. defaults) is in
[`docs/RUNNING.md`](docs/RUNNING.md#environment-variables).

## Pipeline & scheduling

- A sync runs the **full pipeline**: `sync → normalize → context → OpenAI extract` via
  `run_pipeline()`. Extraction is gated on `messages_saved > 0`, and an extraction failure is logged
  but never fails the sync job.
- The worker's **scheduler** enqueues a sync for every active chat every **6 hours**
  (`sync_interval_seconds=21600`). For immediate ingestion, trigger a sync on demand:
  `POST /api/sync/run` (admin), `python scripts/sync_once.py`, or the **Run sync now** button.
- **AI:** OpenAI with Structured Outputs (a strict JSON schema), prompt version **v2** (recall-tuned:
  captures `task` / `request` / `reminder` / `idea` / `knowledge`; ignores chatter and gibberish).
  Per-item **confidence bands**: `≥ 0.90` → candidate status `new`; `0.60–0.90` → `needs_review`;
  `< 0.60` → skipped. The AI only ever creates **Candidates**; a human approval promotes a Candidate
  to a **WorkItem**.

## API (admin/operator surface)

- **Auth:** `POST /api/auth/login` (sets the `aiwip_session` cookie) · `GET /api/auth/me` · `POST /api/auth/logout`
- **Sync:** `POST /api/sync/run` · `GET /api/sync/status` · `GET /api/sync/history`
- **Assignees:** `GET/POST /api/assignees` · `PATCH /api/assignees/{id}`
- **Candidates (review):** `GET /api/candidates` · `GET /api/candidates/{id}` · `PATCH /api/candidates/{id}` (edit) · `POST /api/candidates/{id}/approve` (→ WorkItem) · `POST /api/candidates/{id}/reject`
- **Work items / board:** `GET /api/work-items` · `GET /api/work-items/board` · `POST /api/work-items/{id}/status` · `POST /api/work-items/{id}/labels`
- **Labels:** `GET/POST /api/labels` · **Users:** `GET/POST /api/users`
- **Audit:** `GET /api/audit` · **Evaluation:** `POST/GET /api/evaluation/cases` · `GET /api/evaluation/reports`

Roles: **admin** = everything; **assignee** = view + transition only their own work items.
Full grouped reference with methods, roles, and curl examples: [`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md#rest-api).

## Developer guide

- Monorepo: `core/` (shared) · `api/` · `worker/` · `web/`. Python services are editable-installable.
- **Tests** (need Postgres + Redis on `localhost`; root `conftest.py` forces localhost):
  ```bash
  python -m pytest          # 94 tests
  ```
- **Migrations** (Alembic, in `core/`):
  ```bash
  ALEMBIC_DATABASE_URL=postgresql+psycopg://aiwip:aiwip@localhost:5432/aiwip \
    python -m alembic -c core/alembic.ini upgrade head
  ```
- Build decisions: `build-D1` shared-core monorepo · `build-D2` sync SQLAlchemy · `build-D3` native PG
  enums · `build-D4` dedicated test DBs · `build-D5` Redis server-side sessions · `build-D6` Redis list queue.

## Status & known limitations

**Implemented & tested (94 tests, verified live):** Telegram sync (idempotent), normalization, context
builder, OpenAI extraction (prompt v2 + confidence bands; candidates, never work items), full sync
pipeline with gated extraction, candidate review → WorkItem promotion, Kanban board API, assignees +
resolver, audit, evaluation foundation, Redis queue + 6h scheduler, Docker Compose, and the full
operator web UI (login, review, board, assignees, sync) over a same-origin cookie-auth proxy.

**Known limitations / deferred:**
- Media intelligence (OCR/vision/voice transcription/doc extraction) — attachments are registered as
  metadata placeholders only; no download or processing.
- Semantic, task-level deduplication — not yet implemented.
- Context builder uses a fixed window + time-gap segmentation (no ML topic segmentation).
- AI accuracy targets (90/80) are **north-stars**, not launch gates; gate on reviewer behavior + precision.
- Auth hardening (password reset, rate-limiting, session rotation) deferred.
- Running Alembic migrations inside the container is not wired (run them host-side, see above).
- Additional connectors (Slack / Email / WhatsApp / Discord) are reserved enums only —
  Telegram is the one active source. Adding one: [`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md#connectors).
- Retry/backoff is basic (bounded re-enqueue; a failed `sync_runs` row is the dead-letter record).

## Roadmap

Media intelligence → semantic task-level dedup → eval dataset growth + accuracy tuning →
notifications / outbound integrations → additional connectors (Slack / Email / etc.).
