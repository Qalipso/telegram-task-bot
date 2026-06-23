# Stage 1 Report — Project Foundation

- **Date:** 2026-06-23 · **Branch:** `build/v1` · **Scope:** Full v1.0 (ratified)

## Goal
A runnable project skeleton: all services scaffolded, health checks, base logging, env config,
Docker Compose with Postgres + Redis.

## Implemented
- **Monorepo** on `build/v1`: `core/` (shared), `api/` (FastAPI), `worker/` (Python), `web/` (Next.js).
- **`core` shared package** (`aiwip_core`): `config.py` (pydantic-settings; secrets Optional),
  `logging.py` (stdlib setup), `db.py` (sync SQLAlchemy engine/sessionmaker + declarative `Base`),
  `redis_client.py`, `health.py` (`check_database` / `check_redis`).
- **API** (`aiwip_api`): `GET /health` (liveness, no deps) and `GET /health/ready` (readiness; 503 if
  Postgres/Redis degraded).
- **Worker** (`aiwip_worker`): connectivity heartbeat loop (`run_once` / `run`).
- **Deployment**: `docker-compose.yml` (postgres:16-alpine, redis:7-alpine, api, worker, web) with
  healthchecks + `depends_on: condition: service_healthy`; three `Dockerfile`s (api/worker share the
  `core` package via repo-root build context; web = node:20-alpine build+start); `.env.example`,
  `.gitignore`, `.dockerignore`.
- **Web** (Next.js 16 / React 19, App Router): placeholder dashboard page + `/api/health` route.
- **Tests**: `pytest.ini` + suites for config, health (live/ready/degraded), worker heartbeat, and real
  DB/Redis connection (skip-if-unreachable).

## Not Implemented (by design / deferred)
- DB models + Alembic migrations → **Stage 2**. Auth/roles → **Stage 3**.
- Live Telegram/OpenAI clients → Stages 4 / 8 (creds pending).

## Tests Run / Results
- **Backend** `.venv/bin/python -m pytest` → **9 passed** (after provisioning native Postgres 16 +
  Redis 8 via Homebrew, the two real connection tests now execute and pass; earlier host-only run was
  7 passed / 2 skipped).
- **Live API readiness** against real services: `uvicorn` + `GET /health` → 200; `GET /health/ready` →
  **200 `{"database":{ok:true,"connected"},"redis":{ok:true,"connected"}}`**.
- **Frontend**: `next build` ✓ compiled + type-checked (routes `/`, `/api/health`); **`npm audit` → 0
  vulnerabilities**; runtime smoke `npm start` → `GET /` 200 (renders page), `GET /api/health` 200.

## Bugs Found / Fixed
- **venv console-script shebangs stale** after a dir rename → worked around by invoking via
  `.venv/bin/python -m <tool>` (functional; cosmetic only).
- **Next.js 14.2.5 carried ~15 advisories** (DoS/SSRF/XSS/cache-poisoning) + postcss XSS → **upgraded to
  Next 16.2.9 / React 19.2.7** and pinned `postcss ^8.5.15` via `overrides` → **0 vulnerabilities**.

## Remaining Risks
- **`docker compose up` itself is unverified** (Docker not installed; runtime decision = native
  Postgres/Redis via brew). App↔DB↔Redis connectivity and health/readiness are verified against the
  native services; only the container orchestration (compose, Dockerfiles building, container
  healthchecks) remains for the user to run. The compose/Dockerfiles are authored but unexecuted.
- **Side effect:** `postgresql@16` and `redis` now run as Homebrew services (auto-start at login).
  `brew services stop postgresql@16 redis` to disable.
- Host Python is 3.14 (bleeding-edge); mitigated — containers pin `python:3.12-slim`.
- Live integration (Stages 4/8) needs real credentials + interactive Telethon login.

## Decisions Made
- **build-D1:** Monorepo with a shared `core` package + per-service Dockerfiles (clean imports, separate
  images). Alt (single image, two CMDs) rejected to keep service boundaries explicit.
- **build-D2:** **Sync** SQLAlchemy throughout (≈500 msg/day needs no async DB; FastAPI runs sync routes
  in a threadpool). Revisit only if a real bottleneck appears.

## Files Changed
`.gitignore`, `.dockerignore`, `.env.example`, `docker-compose.yml`,
`core/**` (pyproject + `aiwip_core/{__init__,config,logging,db,redis_client,health}.py` + tests),
`api/**` (pyproject + `aiwip_api/{__init__,main}.py` + `tests/test_health.py` + Dockerfile),
`worker/**` (pyproject + `aiwip_worker/{__init__,main}.py` + `tests/test_smoke.py` + Dockerfile),
`web/**` (package.json, next.config.mjs, tsconfig.json, app/{layout,page}.tsx, app/api/health/route.ts,
Dockerfile, .dockerignore), `pytest.ini`.

## Next Recommended Stage
**Stage 2 — Database Schema & Migrations** (full ~17–19 tables + Alembic), **but** its acceptance
("migrations run cleanly", constraint/relationship tests) requires a real Postgres → resolve the
Docker/DB runtime first.

## Proceed / Do Not Proceed
**PROCEED to Stage 2.** Foundation is green and verified against real Postgres + Redis (9 tests + live
readiness 200). The only unexecuted item is `docker compose up` (the user's chosen runtime is native
brew services; container orchestration is authored, to be run by the user). Stage 2 (schema + Alembic
migrations) is now fully verifiable locally against the native Postgres.
