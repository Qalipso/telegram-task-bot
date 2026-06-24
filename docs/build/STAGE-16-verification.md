# Stage 16 — Backend Verification Gate

**Date:** 2026-06-24
**Branch:** `build/v1`
**Verifier:** independent verification stream (read-only: tests + curl + psql)
**Scope:** Prove the backend test suite is green and the LIVE API contracts hold against the running Docker stack on `http://localhost:8000`.

---

## FINAL VERDICT

> **VERIFICATION FAILED:** The test suite is green (92 passed, exit 0), but the **running API container is a stale build**. It exposes only `auth`, `users`, and `health` routes. **8 of the 14 required live endpoints return `404` because their routers were never built into the deployed image.** The image (`aiwip-api`, built 2026-06-23 20:50) predates the source that wires up all 9 domain routers (`api/src/aiwip_api/main.py`, modified 2026-06-24 09:24). The container must be rebuilt and restarted before the live API contracts can be considered satisfied.

The tests pass because pytest imports the **current on-disk source** (`api/src/aiwip_api`), while the container runs an **older installed copy** baked into site-packages. The two are out of sync.

---

## 1. Full Test Suite

**Command used (ran from repo root):**
```
./.venv/bin/python -m pytest -q
```
(Equivalent to the requested `source .venv/bin/activate && python -m pytest -q`; the venv's
`python` is a symlink to `python3.14`. `conftest.py` points `DATABASE_URL`/`REDIS_URL` at the
exposed localhost ports, so the local run hits the live Postgres/Redis.)

| Metric | Result |
|---|---|
| Passed | **92** |
| Failed | 0 |
| Errors | 0 |
| Warnings | **0** |
| Exit code | **0** |
| Duration | ~17.6s |

**Raw tail:**
```
........................................................................ [ 78%]
....................                                                     [100%]
92 passed in 17.56s
```
Exit code confirmed separately: `exit_code=0`.

**Result: PASS — matches the expected baseline of 92 passed, 0 warnings.**

> Important caveat: this run resolves `aiwip_api` to `/Users/eduardshatalov/Documents/telegram-task-bot/api/src/aiwip_api` (the live source tree with all 9 routers). It does **not** test the artifact running inside `aiwip-api-1`. See §2.

---

## 2. Live API Smoke Test (`http://localhost:8000`)

Cookie jar used: `-c`/`-b` against `/tmp/aiwip_jar.txt`.

| # | Method | Path | Expected | Actual | Body shape | Verdict |
|---|---|---|---|---|---|---|
| 1 | GET | `/health` | 200 | **200** | `{"status":"ok","service":"api","version":"0.1.0"}` | PASS |
| 2 | GET | `/health/ready` | 200 | **200** | `{"status":"ready","checks":{database:ok, redis:ok}}` | PASS |
| 3 | POST | `/api/auth/login` (correct) | 200 + UserOut + `aiwip_session` cookie | **200** | `{"id":1,"email":"admin@aiwip.local","display_name":"Admin","role":"admin"}`; `Set-Cookie: aiwip_session` present (HttpOnly) | PASS |
| 4 | GET | `/api/auth/me` | 200 admin | **200** | admin UserOut (id=1, role=admin) | PASS |
| 5 | POST | `/api/auth/login` (WRONG pw) | 401 | **401** | `{"detail":"Invalid email or password"}` | PASS |
| 6 | GET | `/api/candidates` (no cookie) | 401 | **404** | `{"detail":"Not Found"}` — route not registered (auth gate never reached) | **FAIL** |
| 7 | GET | `/api/candidates` (authed) | 200 list | **404** | `{"detail":"Not Found"}` | **FAIL** |
| 8 | GET | `/api/work-items` (authed) | 200 | **404** | `{"detail":"Not Found"}` | **FAIL** |
| 9 | GET | `/api/work-items/board` (authed) | 200 + 9-status `columns` | **404** | `{"detail":"Not Found"}` | **FAIL** |
| 10 | GET | `/api/sync/status` (authed) | 200 | **404** | `{"detail":"Not Found"}` | **FAIL** |
| 11 | GET | `/api/sync/history` (authed) | 200 | **404** | `{"detail":"Not Found"}` | **FAIL** |
| 12 | GET | `/api/assignees` (authed) | 200 | **404** | `{"detail":"Not Found"}` | **FAIL** |
| 13 | GET | `/api/labels` (authed) | 200 | **404** | `{"detail":"Not Found"}` | **FAIL** |
| 14 | GET | `/api/audit` (authed) | 200 | **404** | `{"detail":"Not Found"}` | **FAIL** |
| 15 | GET | `/api/evaluation/cases` (authed) | 200 | **404** | `{"detail":"Not Found"}` | **FAIL** |

**Bonus checks (existing routes):**

| Method | Path | Expected | Actual | Verdict |
|---|---|---|---|---|
| GET | `/api/users` (no cookie) | 401 | **401** `{"detail":"Not authenticated"}` | PASS (auth gate works) |
| GET | `/api/users` (authed) | 200 list | **200** `[{id:1, admin@aiwip.local, role:admin}]` | PASS |
| POST | `/api/auth/logout` | 200 | **200** `{"status":"logged_out"}` | PASS |

**Smoke-test score: 8 / 16 PASS.** (Health x2, auth login/me/logout, wrong-pw 401, `/api/users` authed + unauth-401 all pass; the 8 domain endpoints all 404.)

### Root cause (investigated, not guessed)

`GET /openapi.json` on the live API lists ONLY:
```
GET  /health
GET  /health/ready
POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/me
GET  /api/users
POST /api/users
```

The container's running module proves why:
- Running module: `/home/appuser/.local/lib/python3.12/site-packages/aiwip_api/main.py`
- Its docstring: *"Stage 1 exposes only health endpoints; domain routers are added from Stage 3+."*
- It calls only `app.include_router(auth_router.router)` and `app.include_router(users_router.router)`.
- Its `routers/` dir contains only `auth.py` and `users.py`.

The current source on disk (`api/src/aiwip_api/main.py`) includes **all 9 routers**
(auth, users, sync, assignees, candidates, work_items, labels, audit, evaluation) and
`api/src/aiwip_api/routers/` contains all 10 router files.

Timestamps:
- `aiwip-api` image created: **2026-06-23T20:55Z** (layer 2026-06-23T20:50Z)
- Disk `main.py` mtime: **2026-06-24 09:24**

→ The image was built before the domain routers were added and was never rebuilt. The
running container is stale relative to HEAD.

**Fix:** `docker compose build api && docker compose up -d api` (or rebuild the whole
stack), then re-run this smoke test.

---

## 3. DB Sanity (`aiwip-postgres-1`, db `aiwip`)

```
docker exec aiwip-postgres-1 psql -U aiwip -d aiwip -c "..."
```

| Table | Count |
|---|---|
| messages | **42** (expected — matches LIVE Telegram sync baseline) |
| users | 1 (admin) |
| candidates | 6 |
| work_items | 0 |
| assignees | 3 |
| labels | 4 |

Postgres/Redis both report healthy via `/health/ready` (`database: connected`, `redis: connected`).
Note: counts beyond `messages`/`users` may reflect demo rows seeded by the parallel frontend
stream; reported as-observed.

---

## Summary

- **Tests:** 92 passed / 0 failed / 0 warnings, exit 0 — **PASS** (but tests run against on-disk source, NOT the deployed container).
- **Live API:** 8/16 smoke checks pass. Auth + health are solid; the 8 domain endpoints 404 because the deployed image predates their routers.
- **DB:** 42 messages confirmed; stack healthy.
- **Blocking issue:** stale `aiwip-api` image. Rebuild + redeploy the API container, then re-verify the live endpoints.

**VERIFICATION FAILED: deployed API container is stale — 8 required domain endpoints (candidates, work-items, work-items/board, sync/status, sync/history, assignees, labels, audit, evaluation/cases) return 404. Rebuild `aiwip-api` from current source and re-run this gate.**
