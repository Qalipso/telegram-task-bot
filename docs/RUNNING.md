# Running & Operations

A practical guide to running the AI Work Intelligence Platform (aiwip), connecting it to Telegram,
ingesting messages, and operating it day to day. For integrating aiwip with other systems (custom
connectors, the AI provider, the REST API, data stores) see [`INTEGRATIONS.md`](INTEGRATIONS.md).

---

## Prerequisites

- **Docker** + Docker Compose v2 (the normal way to run the stack).
- A **Telegram account** and an app registered at <https://my.telegram.org> (gives you
  `api_id` / `api_hash`). The system reads chat history as *your* user via Telethon.
- An **OpenAI API key** — without it the pipeline still syncs and stores messages, but extraction
  produces **zero candidates**.
- For host-side work (tests, the CLI scripts, local `next dev`): **Python 3.12+** and **Node 20+**.

---

## Environment variables

Copy the template and fill it in:

```bash
cp .env.example .env
```

| Var | Default | Purpose |
|---|---|---|
| `APP_ENV` | `local` | Runtime mode label. |
| `LOG_LEVEL` | `INFO` | Log verbosity (`DEBUG` / `INFO` / `WARNING` / …). |
| `POSTGRES_USER` | `aiwip` | Postgres container user. |
| `POSTGRES_PASSWORD` | `aiwip` | Postgres container password — **change for production**. |
| `POSTGRES_DB` | `aiwip` | Postgres database name. |
| `DATABASE_URL` | `…@postgres:5432/aiwip` | DB connection string. Compose overrides host to `postgres`; host-side runs use `localhost`. |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection string. Compose overrides host to `redis`; host-side runs use `localhost`. |
| `WORKER_HEARTBEAT_SECONDS` | `30` | Worker connectivity-heartbeat cadence. |
| `SECRET_KEY` | `dev-insecure-change-me` | Session signing key — **change for production**. |
| `ADMIN_EMAIL` | — | First-admin email (consumed by `python -m aiwip_api.seed`). |
| `ADMIN_PASSWORD` | — | First-admin password (consumed by the seed). |
| `TELEGRAM_API_ID` | — | From my.telegram.org. |
| `TELEGRAM_API_HASH` | — | From my.telegram.org. |
| `TELEGRAM_PHONE` | — | The phone number of the Telegram account (international format). |
| `TELEGRAM_SESSION` | — | Telethon session string — mint with `scripts/telegram_login.py`. Equivalent to a logged-in session; keep secret. |
| `TELEGRAM_CHAT_ID` | — | Default chat to sync (the id `telegram_login.py` prints). |
| `OPENAI_API_KEY` | — | OpenAI key; without it extraction yields no candidates. |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model for extraction. |

`SECRET_KEY` is not in `.env.example` but is read by config — set it explicitly for any non-local
deployment. `sync_interval_seconds` (the scheduled-sync cadence, default 6 h) is a config default, not
an `.env` field; override it via environment only if you have a reason to.

> `.env` is gitignored. Never commit it, and never paste `TELEGRAM_SESSION`, `OPENAI_API_KEY`, or
> passwords into source, logs, or chat.

---

## First run

### 1. Start the stack

```bash
cp .env.example .env          # then edit secrets
docker compose up -d --build  # postgres, redis, api, worker, web
```

Wait for health to come up:

```bash
docker compose ps                                   # all services "healthy"
curl -s http://localhost:8000/health                # {"status":"ok",...}
curl -s http://localhost:8000/health/ready          # {"status":"ready", checks:{database,redis}}
```

### 2. Seed the first admin

```bash
docker compose exec -e ADMIN_EMAIL=you@example.com -e ADMIN_PASSWORD='change-me' \
  api python -m aiwip_api.seed
# → "admin ready: you@example.com (id=1)"
```

The seed is idempotent (re-running returns the existing admin). A development admin used during this
project is `admin@aiwip.local` / `aiwip-admin-dev` — that is an **example only; change it for
production**.

### 3. Connect Telegram

`telegram_login.py` is interactive (Telegram texts you a login code), so **run it on the host**, not
in a container. From the repo root with your virtualenv active:

```bash
# .env already has TELEGRAM_API_ID / TELEGRAM_API_HASH / TELEGRAM_PHONE
python scripts/telegram_login.py
# enter the code Telegram sends (and your 2FA password if you have one)
```

It writes `TELEGRAM_SESSION` back into `.env` (the session string is never printed) and lists your
recent chats with their ids.

### 4. Pick the chat and set `TELEGRAM_CHAT_ID`

Copy the id of the chat you want to ingest from the printed list into `.env`:

```
TELEGRAM_CHAT_ID=-1001234567890
```

Because the worker reads `.env` at process start, recreate it so it picks up the new session + chat id:

```bash
docker compose up -d worker
```

### 5. Trigger the first sync

Pick whichever is convenient:

- **UI:** open <http://localhost:3000>, log in, go to **Sync**, click **Run sync now**.
- **API:** `POST /api/sync/run` (admin) — see [Triggering & inspecting syncs](#triggering--inspecting-syncs).
- **CLI (host):** `python scripts/sync_once.py` (uses `TELEGRAM_CHAT_ID`, or pass a chat id arg).

A sync runs the full pipeline (`sync → normalize → context → OpenAI extract`). Extraction runs **only
when new messages were saved**, so candidates appear after the first sync that ingests fresh history.
Open the **Review queue** to triage them.

---

## Serving the web UI

The browser talks to a **same-origin Next.js proxy** (`web/app/api/[...path]/route.ts`) that forwards
`/api/*` to `API_BASE` and passes the `aiwip_session` httpOnly cookie through. You never point the
browser at port 8000 directly.

- **Docker (default):** the UI is built into the `web` image and served at <http://localhost:3000>;
  `API_BASE=http://api:8000`. **After any UI source change, rebuild the image:**
  ```bash
  docker compose build web && docker compose up -d web
  ```
- **Local dev (fast iteration):**
  ```bash
  cd web
  npm install
  npm run dev          # http://localhost:3000, proxies to http://localhost:8000
  ```
  For this to reach the API, run the API on `localhost:8000` — either the Docker `api` service (its
  port is published) or a host-side `uvicorn`.

---

## Triggering & inspecting syncs

**Trigger a sync (admin):**

```bash
# log in first to get the session cookie into a cookie jar
curl -s -c cookies.txt -X POST http://localhost:8000/api/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"you@example.com","password":"change-me"}'

# enqueue a sync for the default chat (TELEGRAM_CHAT_ID), or pass {"chat_id": ...}
curl -s -b cookies.txt -X POST http://localhost:8000/api/sync/run \
  -H 'content-type: application/json' -d '{}'
# → {"status":"queued","chat_id":...,"queue_length":1}
```

**Inspect state and history:**

```bash
curl -s -b cookies.txt http://localhost:8000/api/sync/status   # queue length, latest run, per-chat sync_state
curl -s -b cookies.txt http://localhost:8000/api/sync/history  # recent sync_runs (read / saved counts, status, errors)
```

`POST /api/sync/run` only **enqueues** a job; the worker picks it up from the Redis queue and runs the
pipeline. Watch it land with `docker compose logs -f worker`.

**CLI alternative (host, live):**

```bash
DATABASE_URL=postgresql+psycopg://aiwip:aiwip@localhost:5432/aiwip \
REDIS_URL=redis://localhost:6379/0 \
python scripts/sync_once.py            # or: python scripts/sync_once.py <chat_id>
```

`sync_once.py` does a sync only (no extraction); use `POST /api/sync/run` or the UI button for the full
pipeline.

---

## Seeding demo data & dry-running extraction

**Demo data (no OpenAI key needed)** — inserts illustrative assignees, labels, and candidates linked to
real synced messages so the review queue and board render content:

```bash
docker cp scripts/seed_demo.py aiwip-api-1:/tmp/seed_demo.py
docker exec aiwip-api-1 python /tmp/seed_demo.py
```

It is idempotent (re-running does nothing once the demo candidates exist). Approval is left to be done
through the UI to demonstrate the live flow.

**Dry-run extraction (needs `OPENAI_API_KEY` in the worker)** — builds the same context window the live
pipeline would, calls the LLM, and prints the candidates it *would* create **without writing anything**:

```bash
docker cp scripts/extract_dryrun.py aiwip-worker-1:/tmp/dryrun.py
docker exec aiwip-worker-1 python /tmp/dryrun.py            # default internal chat id = 1
docker exec aiwip-worker-1 python /tmp/dryrun.py 1
```

Use it to validate prompt/recall changes against real messages without creating duplicate candidates.
It prints each candidate's confidence band (`new` / `needs_review` / `SKIPPED`).

---

## Tests & migrations

**Tests** (94 pytest tests). They need Postgres + Redis reachable on `localhost`; the root
`conftest.py` forces localhost connection strings:

```bash
# with the Docker postgres/redis up (ports published), from the repo root:
python -m pytest          # 94 tests
```

Tests run against **on-disk source**, independent of what the running containers serve — this is why a
green test run does not prove the deployed container is current (see [Troubleshooting](#troubleshooting)).

**Migrations** (Alembic lives in `core/`). Run them host-side against the database:

```bash
ALEMBIC_DATABASE_URL=postgresql+psycopg://aiwip:aiwip@localhost:5432/aiwip \
  python -m alembic -c core/alembic.ini upgrade head
```

Running Alembic *inside* the container is not yet wired; apply migrations from the host.

---

## Monitoring & logs

- **Health endpoints:** `GET /health` (liveness, never touches dependencies) and `GET /health/ready`
  (readiness — checks Postgres + Redis, returns `503` if degraded). Both are also used as container
  healthchecks.
- **Service status:** `docker compose ps` (shows the `healthy` / `unhealthy` state of each service).
- **Logs:**
  ```bash
  docker compose logs -f api                 # follow the API
  docker compose logs -f worker              # follow sync / extraction
  docker compose logs --tail=100 web
  ```
  All services use the `json-file` driver with rotation (10 MB × 3–5 files).
- **Resource usage:** `docker stats`.

More detail (resource limits, optional Prometheus/Grafana, log aggregation) is in
[`../MONITORING.md`](../MONITORING.md); deployment/scaling guidance is in
[`../DEPLOYMENT.md`](../DEPLOYMENT.md).

---

## Troubleshooting

### Stale container serving old code
**Symptom:** you changed source, tests pass, but the running app behaves like the old code (most
common with the UI).
**Cause:** the `api` / `web` / `worker` images bundle source at build time; `docker compose up -d`
alone does **not** rebuild them.
**Fix:** rebuild and recreate the affected service:
```bash
docker compose build web && docker compose up -d web        # (or api / worker)
```

### Zero candidates after a sync
- **`OPENAI_API_KEY` unset** in the worker → extraction can't run; the sync still stores messages but
  creates no candidates. Set the key in `.env` and recreate the worker.
- **No *new* messages saved** → extraction is gated on `messages_saved > 0`, so a sync that read only
  already-stored messages intentionally creates nothing. Check `GET /api/sync/history` (`messages_saved`).
- **Window is only chatter** → prompt v2 deliberately returns no candidates for greetings, reactions,
  jokes, emoji-only, or gibberish. Confirm with `scripts/extract_dryrun.py`.
- **All items below the band** → items with confidence `< 0.60` are skipped by design.

### Empty review queue but messages exist
The scheduler only runs every **6 hours**. If you just want candidates *now*, trigger an on-demand sync
(UI **Run sync now**, `POST /api/sync/run`, or `scripts/sync_once.py`) rather than waiting for the
scheduled run. Remember a sync only extracts when it saved **new** messages.

### Telegram session invalid / connector error
`TelegramConnector` raises if `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` / `TELEGRAM_SESSION` are missing,
and sync runs fail if the session has been revoked or expired. Re-mint the session:
```bash
python scripts/telegram_login.py        # writes a fresh TELEGRAM_SESSION to .env
docker compose up -d worker             # recreate so it reloads .env
```

### Backend unreachable from the UI (`502`)
The proxy returns `{"detail":"Backend API is unreachable"}` with `502` when it can't reach `API_BASE`.
In Docker, confirm the `api` service is healthy; in local `next dev`, confirm an API is listening on
`http://localhost:8000`.

### Worker looks idle
That is normal. The worker BRPOPs the Redis queue with a 5 s timeout and logs a heartbeat every
`WORKER_HEARTBEAT_SECONDS`; with no jobs queued it simply waits. Enqueue a sync to give it work.

### Login fails
Make sure you seeded an admin (step 2) and are POSTing JSON `{"email","password"}` to
`/api/auth/login`. A `401` means the email/password didn't match a user.
