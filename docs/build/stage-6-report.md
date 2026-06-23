# Stage 6 Report — Assignee Management

- **Date:** 2026-06-23 · **Branch:** `build/v1` · **Commit:** `0eb99cf`

## Goal
Manage the finite list of possible assignees (CRUD, active/inactive) and provide the resolver
foundation the AI pipeline uses to map mentions → assignees.

## Implemented
- **`/api/assignees`** (admin-only): `GET` (with `?active=` filter), `POST` (create), `PATCH` (edit /
  deactivate). Fields: `display_name`, `telegram_user_id`, `telegram_username`, `aliases[]`, `user_id`,
  `is_active`.
- **`aiwip_worker.resolver.resolve_assignees`**: case-insensitive match of a mention (`@username` /
  display name / alias) against **active** assignees; returns all matches (0 → needs-review/unassigned,
  >1 → ambiguous). Exact normalized matching for MVP.

## Tests Run / Results
- `.venv/bin/python -m pytest` → **56 passed** vs the Docker Postgres + Redis.
- Stage 6: CRUD + active filter; role enforcement (assignee 403, unauth 401, 404 on missing); resolver
  by username/alias/display-name, active-only exclusion, ambiguous (multiple), empty/unknown.

## Not Implemented (deferred)
- **Assignee UI** — deferred to a consolidated front-end pass (with Stage 9 review UI + Stage 10 board);
  the API + resolver (what Stages 7–8 depend on) are complete.

## Decisions Made
- Deactivate via `PATCH is_active=false` (no hard delete) — preserves history and FK integrity.
- Resolver does **exact normalized** matching (strip/`@`/lowercase) across username + display name +
  aliases; fuzzy matching is a later refinement.

## Files Changed
`api/src/aiwip_api/{schemas.py,routers/assignees.py,main.py}`, `worker/src/aiwip_worker/resolver.py`,
`api/tests/test_assignees.py`, `worker/tests/test_resolver.py`.

## Next Recommended Stage
**Stage 7 — Context Builder** (assemble analysis windows from stored normalized messages: last ~20 +
reply/quote chains; topic continuation; context summary/confidence). No external creds. Then
**Stage 8 (OpenAI candidates — needs `OPENAI_API_KEY`)**.

## Proceed / Do Not Proceed
**PROCEED to Stage 7.** Assignee management + resolver complete and verified (56 tests).
