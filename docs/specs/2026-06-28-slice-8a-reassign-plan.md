# Slice 8a — Reassign Work Item — Implementation Plan

> **Status:** [Planned] — PLAN ONLY. No feature code may be written until this plan is
> approved (plan→work ordering, Iron Law §1.4).
> **Date:** 2026-06-28 · **Gap closed:** #4 (assignees are fixed at candidate→approve;
> the Board drawer shows them read-only).
> **Pattern precedent:** Slices 6 & 7 — admin-only audited endpoint + forward-only additive
> enum migration. This slice follows that template exactly.

---

## 0. Goal & scope

Let an **admin** add/remove the assignees of an **existing** work item from the Board drawer.

| In scope | Out of scope (do NOT touch) |
|---|---|
| `PUT /api/work-items/{id}/assignees` (admin-only, audited) | bot/ (`bot/**`) — no edits |
| New request schema + audit action + migration | worker/ — no edits |
| Drawer assignee editor (add/remove/save) | candidate assignee flow (already exists) |
| `apiPut` helper in `web/app/lib/api.ts` | label edit/delete (deferred Slice 8 remainder) |
| Tests in `api/tests/test_work_items.py` | any non-additive `core/` change |

**Verified repo facts (inspected 2026-06-28):**
- Alembic head = `e8a1c25b3f07` (`add_audit_action_candidate_marked_duplicate`).
- `AuditAction` enum (`core/src/aiwip_core/models.py:173`) has no `work_item_reassigned` value yet.
- `WorkItemAssignee` join model exists (`models.py:529`) with `is_primary`.
- `_set_candidate_assignees` (`candidates.py:49`) validates active ids → 422, then replaces the
  set (first = primary). It is **candidate-specific** (mutates `CandidateAssignee` +
  `missing_fields`), so we extract only its **validation** into a shared helper, not the whole body.
- `GET /api/assignees?active=true` already exists (admin-only, `routers/assignees.py:16`) — the
  drawer editor reuses it for the catalog; no new GET endpoint needed.
- `enrich.work_items_out` returns `assignees` as display-name strings; the drawer's
  `GET /api/work-items/{id}` returns the rich `assignees: CandidateAssigneeRef[]` it edits.
- `web/app/lib/api.ts` has `apiGet/apiPost/apiPatch` only — **no `apiPut`/`apiDelete`**.

---

## 1. Endpoint design

**`PUT /api/work-items/{work_item_id}/assignees`** — admin-only, audited, replace-set semantics.

| Aspect | Decision |
|---|---|
| Method/path | `PUT …/assignees` — replace-the-collection is idempotent; PUT is the REST-correct verb. Justifies adding `apiPut` (§5). |
| Auth | `Depends(auth.require_admin)` (same as `edit_work_item`). Non-admin → **403**. |
| Body | `{ "assignee_ids": [int, …] }` — ordered; **first id = primary** (D25). |
| Semantics | **Replace** the full `WorkItemAssignee` set for this item (delete-all + re-insert). |
| Empty list | **Allowed** → clears all assignees (item becomes unassigned). See Risks §7. |
| Response | `200` + `WorkItemOut` (same shape `edit_work_item` returns), so the drawer can use the response or refetch. |
| 404 | Unknown `work_item_id` → `404 "Work item not found"` (plain `db.get`, like `edit_work_item` — **not** `_get_visible_or_404`; admins manage all items). |
| 422 | Any id unknown OR `is_active=False` → `422` with `Unknown or inactive assignee id(s): [...]`, **before any mutation**. |

**Reuse / generalize (no duplication of validation):**
Extract the active-id validation from `_set_candidate_assignees` into a shared helper so both
sites share one source of truth.

```python
# core/src/aiwip_core/assignees.py  (NEW small module) — or api/src/aiwip_api/_assignees.py
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from aiwip_core.models import Assignee

def validate_active_assignee_ids(db: Session, assignee_ids: list[int]) -> None:
    """Raise 422 if any id is unknown or inactive. No-op for an empty list."""
    if not assignee_ids:
        return
    active_ids = set(db.execute(
        select(Assignee.id).where(Assignee.id.in_(assignee_ids), Assignee.is_active.is_(True))
    ).scalars().all())
    invalid = [aid for aid in assignee_ids if aid not in active_ids]
    if invalid:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Unknown or inactive assignee id(s): {invalid}",
        )
```

Then `_set_candidate_assignees` (`candidates.py`) is refactored to call
`validate_active_assignee_ids(db, assignee_ids)` instead of its inline block — **behavior
identical**, existing candidate tests stay green (no candidate test changes). The work-item
setter lives in `work_items.py`:

```python
# api/src/aiwip_api/routers/work_items.py
def _set_work_item_assignees(db: Session, wi: WorkItem, assignee_ids: list[int]) -> None:
    validate_active_assignee_ids(db, assignee_ids)
    db.query(WorkItemAssignee).filter_by(work_item_id=wi.id).delete()
    for i, aid in enumerate(assignee_ids):
        db.add(WorkItemAssignee(work_item_id=wi.id, assignee_id=aid, is_primary=(i == 0)))

@router.put("/{work_item_id}/assignees", response_model=WorkItemOut)
def reassign_work_item(
    work_item_id: int,
    payload: ReassignWorkItemRequest,
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(auth.get_db),
) -> WorkItem:
    wi = db.get(WorkItem, work_item_id)
    if wi is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Work item not found")
    before = _assignee_ids_snapshot(db, wi)            # ordered id list, primary first
    _set_work_item_assignees(db, wi, payload.assignee_ids)
    db.flush()
    audit.record_audit(
        db, admin.id, AuditAction.work_item_reassigned, AuditEntityType.work_item, wi.id,
        before={"assignee_ids": before}, after={"assignee_ids": payload.assignee_ids},
    )
    db.commit()
    db.refresh(wi)
    return wi
```

`_assignee_ids_snapshot(db, wi)` = small helper returning the current ids primary-first, mirroring
`_editable_snapshot`'s role for the audit `before`/`after`.

**Files touched:** `api/src/aiwip_api/routers/work_items.py` (add helper, endpoint, import
`WorkItemAssignee` already present, import `validate_active_assignee_ids`, `ReassignWorkItemRequest`),
`api/src/aiwip_api/routers/candidates.py` (swap inline validation → shared helper),
new `core/src/aiwip_core/assignees.py`.

---

## 2. Schema

`api/src/aiwip_api/schemas.py` — new request model (place near `UpdateWorkItemRequest`):

```python
class ReassignWorkItemRequest(BaseModel):
    """Replace a work item's assignee set (admin-only). First id = primary (D25).
    Empty list clears all assignees."""
    assignee_ids: list[int] = Field(default_factory=list)
```

No response schema needed — reuse `WorkItemOut`.

---

## 3. Audit + migration

**3a. Enum value** — `core/src/aiwip_core/models.py`, append to `AuditAction` (after
`work_item_edited`, line ~182):

```python
    work_item_reassigned = "work_item_reassigned"
```

**3b. Migration** — new file
`core/alembic/versions/<rev>_add_audit_action_work_item_reassigned.py`, chained on the
current head **`e8a1c25b3f07`** (copy `d4e7b2c9f1a3` verbatim, swap the value):

```python
"""add audit_action work_item_reassigned

Revision ID: f1a2b3c4d5e6        # generate a fresh 12-hex id; do NOT reuse this literal
Revises: e8a1c25b3f07
Create Date: 2026-06-28 …
"""
from typing import Sequence, Union
from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "e8a1c25b3f07"
branch_labels = None
depends_on = None

def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'work_item_reassigned'")

def downgrade() -> None:
    pass  # forward-only (Decisions §16.2): Postgres can't DROP an enum value
```

> Generate the revision id with `python -m alembic revision -m "..."` (or any fresh 12-hex) and
> set `down_revision = "e8a1c25b3f07"`. After adding, the new head is this revision.

**3c. Live-DB step (deploy, §6)** — the test DB is built with `create_all()` (enum already has the
new member once the model is edited), but **prod runs migrations**. On the live box, after pulling:

```sh
docker compose exec api python -m alembic upgrade head
```

If the api image bakes code, **rebuild api first** (`docker compose build api`) so the new enum
member exists in the SQLAlchemy `Enum(...)` binding before any insert (see Risks §7, create_all gotcha).

---

## 4. Tests — `api/tests/test_work_items.py`

Reuse helpers `_login_user`, `_work_item`; seed assignees with `m.Assignee` + `m.WorkItemAssignee`.
Run: stop worker+bot containers, then `.venv/bin/python -m pytest api/tests/test_work_items.py`
(local Postgres `aiwip_test`).

| # | Test name | Asserts |
|---|---|---|
| 1 | `test_reassign_replaces_assignees_happy_path` | PUT with `[a2,a3]` → 200; GET detail shows exactly a2 (primary) + a3; a1 gone |
| 2 | `test_reassign_writes_audit_row` | one `Audit` row, action `work_item_reassigned`, entity `work_item`, `before`/`after` assignee_ids correct |
| 3 | `test_reassign_first_id_is_primary` | PUT `[a2,a1]` → a2 `is_primary=True`, a1 `False` |
| 4 | `test_reassign_empty_list_clears` | PUT `[]` → 200; detail `assignees == []` (confirms empty allowed) |
| 5 | `test_reassign_rejects_unknown_assignee_id` | PUT `[99999]` → **422**; assignee set unchanged (no partial mutation) |
| 6 | `test_reassign_rejects_inactive_assignee_id` | seed `is_active=False` assignee → PUT → **422** |
| 7 | `test_reassign_requires_admin` | non-admin session → **403** |
| 8 | `test_reassign_unknown_work_item_404` | PUT to missing id → **404** |

TDD: write each Red first, confirm it fails for the right reason, then implement.

---

## 5. Frontend — `web/app/board/page.tsx` (`WorkItemDrawer`) + `web/app/lib/api.ts`

**5a. `apiPut` decision → ADD it.** One line; keeps the client REST-correct for replace-set.
`web/app/lib/api.ts`:

```ts
export const apiPut = <T>(path: string, body?: unknown) => request<T>("PUT", path, body);
```

**5b. Drawer editor.** Keep the existing **read view** (`assignee-chip` row, lines ~547–557)
intact. Add an editable mode beside it, mirroring the existing Labels add-row pattern:

- New state in `WorkItemDrawer`: `assigneeCatalog: Assignee[]`, `editingAssignees: boolean`,
  `draftIds: number[]`.
- Load catalog lazily on entering edit: `apiGet<Assignee[]>("/api/assignees?active=true")`
  (admin-only; same as label catalog load, with its toast-on-fail).
- UI: an "Edit" affordance on the Assignees row → renders current assignees as removable chips
  (✕ removes from `draftIds`) + a `<select>` of catalog members **not already chosen** to add.
  First chip = primary (visually labelled, reordering optional/out of scope — primary = `draftIds[0]`).
- **Save** → `await apiPut(\`/api/work-items/${wi.id}/assignees\`, { assignee_ids: draftIds })`
  → `await refetch()` (existing fn, line 425) → `onBoardChanged()` → success toast
  `"Assignees updated."`. On error: error toast with Retry (match `assignLabel` pattern).
- Cancel → discard `draftIds`, exit edit mode.

**5c. Types** — `web/app/lib/types.ts` already has `Assignee` and
`WorkItemDetail.assignees: CandidateAssigneeRef[]`. No type change required (the editor maps
`CandidateAssigneeRef.assignee_id` ↔ `Assignee.id`).

**Files touched:** `web/app/lib/api.ts`, `web/app/board/page.tsx`. (CSS reuses existing
`.assignee-chip`, `.chip-row`, `.add-label-row`, `.btn` classes — no new stylesheet needed; add a
remove-✕ button styled with existing ghost-button classes.)

---

## 6. Gates & Definition of Done

| Gate | Requirement |
|---|---|
| TDD green | All 8 tests in §4 written Red-first, then green. Candidate tests unchanged & still green after the validation refactor. Report exact `pytest` command + counts; label `[Not verified]` anything unrun. |
| Security review | New **public endpoint** + **migration** + **auth surface** → mandatory `security-reviewer` pass before ship (`security-sensitive-changes`). Check: admin-only enforced, 422-before-mutation (no partial writes), `assignee_ids` not trusted (validated against active set), audit row written. |
| Human approval | Endpoint + DB-enum change are deep-work triggers → **explicit approval before implementation** (per CLAUDE.md). This plan IS the approval artifact. |
| Live deploy | `docker compose build api` → `alembic upgrade head` → restart api. Verify enum member present (`SELECT enum_range(NULL::audit_action);`). |
| E2E verify on :3100 | Open drawer for a real WI → add + remove an assignee → Save → chips update, toast shows; reload page → persisted; check `audit` table has a `work_item_reassigned` row. Capture as evidence (`evidence-first-completion`). |
| Scope-guard diff | `git diff --stat`: **no** `bot/` or `worker/` files; `core/` change is **additive only** (one enum member + one migration); frontend limited to `api.ts` + `board/page.tsx`. |

---

## 7. Risks & mitigations

| Risk | Mitigation |
|---|---|
| **Empty list clears all assignees** — is that intended? | Yes by design (admin can unassign). Covered by test #4. If product says no, add a `min_length=1` guard later — flag at approval. |
| **Primary handling** — reordering primary isn't a first-class UI action | Primary = `draftIds[0]`; remove-then-re-add reorders. Acceptable for 8a; full drag-reorder is out of scope. |
| **`apiPut` addition** — new client verb | One-line, mirrors existing helpers; alternative (POST `…/assignees`) avoids it but is less REST-correct for replace. Chosen: add `apiPut`. |
| **create_all-vs-alembic enum gotcha** | Test DB (`create_all`) gets the member from the model edit; **prod needs the migration**. DoD §6 forces `build api` + `alembic upgrade head` + an `enum_range` check before E2E. |
| **Partial mutation on bad id** | Validation (`validate_active_assignee_ids`) runs **before** any delete/insert → 422 leaves the set untouched (test #5/#6). |
| **Refactor of `_set_candidate_assignees`** could regress candidates | Refactor extracts validation only; run candidate tests (`test_patch_rejects_nonexistent_assignee_id`, `test_patch_rejects_inactive_assignee_id`) to confirm green. |
| **Visibility scope** | Admins manage all items → use plain `db.get`, not `_get_visible_or_404`, matching `edit_work_item`. |

---

## 8. Handoff

Approved plan → `implementation-engineer` (single focused PR). Security surface →
`security-reviewer` before merge. Sequence: migration + model → schema → shared helper +
endpoint → tests (TDD) → frontend → deploy + E2E.
