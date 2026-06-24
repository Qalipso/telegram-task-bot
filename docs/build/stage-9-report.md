# Stage 9 Report — Candidate Review

- **Date:** 2026-06-23 · **Branch:** `build/v1` · **Commit:** `8f08b3f`

## Goal
Let an admin review, edit, approve, and reject AI candidates; approval creates a WorkItem; actions
are audited.

## Implemented
- **`/api/candidates`** (admin-only): `GET` list (`?status` filter), `GET /{id}` detail (with assignee
  + message links), `PATCH /{id}` edit (→ `status=edited`), `POST /{id}/approve`, `POST /{id}/reject`.
- **`core.promotion.approve_candidate`**: candidate → **WorkItem** (`status=inbox`); promotes
  `candidate_assignees → work_item_assignees` (carry `is_primary`, drop confidence — D25) and
  `candidate_labels → work_item_labels`; snapshots reasoning/confidence; sets candidate `approved`.
- **`core.audit.record_audit`** + audit on `candidate_edited` (before/after), `candidate_approved`,
  `candidate_rejected`.
- Guards: approved candidates are immutable (edit/reject → 409); rejected candidates are retained.

## Tests Run / Results
- `.venv/bin/python -m pytest` → **74 passed** vs Docker Postgres + Redis.
- Stage 9 (6): list + status filter + detail; edit→edited + audit before/after; approve→WorkItem with
  promoted assignees + candidate approved + audit + re-approve 409; reject retained + audit; role
  enforcement (assignee 403, unauth 401).

## Not Implemented (deferred)
- Review **UI** (queue, confidence/missing-field indicators) → consolidated front-end pass.
- WorkItem list/**board** + status transitions → **Stage 10**. Audit **query/view** API → **Stage 11**.

## Decisions Made
- Approve is the only path that creates a WorkItem (AI never does — confirmed end-to-end).
- Edit records a structured before/after diff of the editable fields in `audit_logs`.

## Files Changed
`core/src/aiwip_core/{audit,promotion}.py`, `api/src/aiwip_api/{schemas.py,routers/candidates.py,main.py}`,
`api/tests/test_candidates.py`.

## Next Recommended Stage
**Stage 10 — WorkItem & Kanban Board** (WorkItem list/board API + status transitions + audit on
`work_item_status_changed`; assignee visibility). Then **Stage 11** (audit view), **Stage 12** (eval).

## Proceed / Do Not Proceed
**PROCEED to Stage 10.** Review flow complete and verified (74 tests); the candidate→WorkItem bridge works.
