# AI Work Intelligence Platform

Turns Telegram work discussions into reviewed **Work Items** through a human-in-the-loop AI pipeline:

```
Telegram → Sync → Normalize → Context → OpenAI candidates → Human review → WorkItem → Kanban board
```

Core principle: **the AI never creates final Work Items** — every candidate requires human approval.
Precision over recall: a false task is worse than a missed weak signal.

> Product/spec docs live in [`docs/`](docs/) (EN canonical + RU). Per-stage build reports are in
> [`docs/build/`](docs/build/). The authoritative spec is [`docs/system-spec.md`](docs/system-spec.md).

## Architecture

| Service | Tech | Role |
|---|---|---|
| `api` | FastAPI | REST: auth, candidate review, work items/board, assignees, sync control, audit, evaluation |
| `worker` | Python + Telethon | Telegram sync, normalization, context builder, OpenAI extraction, job consumer + 6h scheduler |
| `core` | shared package | SQLAlchemy models (19 tables), config, db, redis, logging, audit, promotion |
| `web` | Next.js 16 / React 19 | Frontend (dashboard placeholder; full UI is the next milestone) |
| `postgres` 16 / `redis` 7 | — | data + job queue/sessions |

## Quick start (Docker)

```bash
cp .env.example .env          # fill secrets (see below)
docker compose up -d --build  # postgres, redis, api, worker, web
# api → http://localhost:8000 (GET /health, /health/ready)
# web → http://localhost:3000
```

Seed the first admin (after the stack is up):

```bash
docker compose exec api python -m aiwip_api.seed   # uses ADMIN_EMAIL / ADMIN_PASSWORD from .env
```

## Environment (`.env`)

| Var | Purpose |
|---|---|
| `POSTGRES_USER/PASSWORD/DB` | Postgres container credentials |
| `DATABASE_URL` / `REDIS_URL` | service connection strings (compose overrides to in-network hosts) |
| `SECRET_KEY` | session signing |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | first-admin seed |
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` / `TELEGRAM_PHONE` | from https://my.telegram.org |
| `TELEGRAM_SESSION` | Telethon session string — mint with `python scripts/telegram_login.py` (interactive) |
| `TELEGRAM_CHAT_ID` | target chat to sync |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | OpenAI (default `gpt-4o-mini`) |

Secrets go in `.env` only (gitignored) — never in source or chat. `TELEGRAM_SESSION` is equivalent to a
logged-in session; keep it secret.

## Telegram setup

```bash
# 1. create an app at my.telegram.org → put api_id/api_hash/phone in .env
python scripts/telegram_login.py   # interactive: enter the code Telegram sends; writes TELEGRAM_SESSION + lists chats
# 2. set TELEGRAM_CHAT_ID in .env, then trigger a sync:
python scripts/sync_once.py        # or POST /api/sync/run (admin)
```

## Admin guide (API)

- **Auth:** `POST /api/auth/login` (email+password, sets session cookie) · `GET /api/auth/me` · `POST /api/auth/logout`
- **Sync:** `POST /api/sync/run` · `GET /api/sync/status` · `GET /api/sync/history`
- **Assignees:** `GET/POST /api/assignees` · `PATCH /api/assignees/{id}`
- **Candidates (review):** `GET /api/candidates` · `GET /api/candidates/{id}` · `PATCH` (edit) · `POST /{id}/approve` (→ WorkItem) · `POST /{id}/reject`
- **Work items / board:** `GET /api/work-items` · `GET /api/work-items/board` · `POST /{id}/status` · `POST /{id}/labels`
- **Labels:** `GET/POST /api/labels`
- **Audit:** `GET /api/audit` · **Evaluation:** `POST/GET /api/evaluation/cases` · `GET /api/evaluation/reports`

Roles: **admin** = everything; **assignee** = view + transition only their own work items.

## Developer guide

- Monorepo: `core/` (shared) · `api/` · `worker/` · `web/`. Python services are editable-installable.
- **Tests** (need Postgres + Redis on `localhost`; root `conftest.py` forces localhost):
  ```bash
  python -m pytest          # 92 tests
  ```
- **Migrations** (Alembic, in `core/`):
  ```bash
  ALEMBIC_DATABASE_URL=postgresql+psycopg://aiwip:aiwip@localhost:5432/aiwip \
    python -m alembic -c core/alembic.ini upgrade head
  ```
- Build decisions: `build-D1` shared-core monorepo · `build-D2` sync SQLAlchemy · `build-D3` native PG
  enums · `build-D4` dedicated test DBs · `build-D5` Redis server-side sessions · `build-D6` Redis list queue.

## Status & known limitations

**Implemented & tested (92 tests, verified live):** Telegram sync (idempotent), normalization, context
builder, OpenAI extraction (candidates, never work items), candidate review → WorkItem, Kanban board API,
assignees + resolver, audit, evaluation foundation, Redis queue + scheduler, Docker Compose.

**Known limitations / deferred:**
- **Frontend UI** is a placeholder — the review queue, board, assignee admin, and sync dashboard are the
  next milestone (all backend APIs exist).
- Media intelligence (OCR/vision/voice transcription/doc extraction) — attachments are registered as
  placeholders only.
- Context builder uses a fixed window + time-gap segmentation (no ML topic segmentation).
- AI accuracy targets (90/80) are **north-stars**, not launch gates; gate on reviewer behavior + precision.
- Auth hardening (password reset, rate-limiting, session rotation) and alembic-in-container deferred.
- Retry/backoff is basic (bounded re-enqueue; failed `sync_runs` is the dead-letter record).

## Roadmap

Frontend pass → media intelligence → semantic task-level dedup → eval dataset growth + accuracy tuning →
notifications → additional connectors (Slack/Email/etc.).
