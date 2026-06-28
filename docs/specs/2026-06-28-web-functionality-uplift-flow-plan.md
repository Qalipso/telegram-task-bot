# Web Console Functionality Uplift — Coordinating Flow Plan

> **Type:** Planning artifact (flow / coordination document). **Do NOT implement from this file directly** —
> each remaining slice is dispatched, gated, and approved per the loop below.
> **Date:** 2026-06-28 · **Repo:** `/Users/eduardshatalov/Documents/telegram-task-bot` ·
> **Branch:** `feat/web-ui-uplift` · **Mode:** Hybrid (human approval per backend slice).
> **Predecessor spec:** `docs/specs/2026-06-27-web-ui-uplift-design.md`.

This is the single coordinating document for closing the remaining "AI Work Intelligence Platform"
web-console functionality gaps. The orchestrator owns coordination, gates, and deploy decisions;
specialist agents do the work.

---

## 0. HARD SCOPE GUARD (encode in every slice)

| Area | Rule |
|---|---|
| **Frontend** | Lives in `web/app/**` only. |
| **Backend** | May touch `api/`, `core/` **additively only** (no destructive edits to existing contracts). |
| **Backend = gate** | **Every backend slice is an approval gate** (Hybrid: human approval per slice) **and** requires `security-reviewer`. |
| **Forbidden** | **NEVER edit `bot/` or `worker/`.** Any diff touching these = automatic STOP + escalate. |
| **Scope-guard check** | Every slice ends with a `git diff --name-only` review: confirm files ⊆ allowed set, zero `bot/` or `worker/` paths. |

### Environment / test reality (encode in every slice)

| Surface | How to verify |
|---|---|
| **`web/`** | **No test runner.** Verify via `tsc --noEmit` + `next build` + **browser preview on `:3100`**. |
| **`api/`** | `pytest` against **local Postgres `aiwip_test`**: `.venv/bin/python -m pytest`. |
| **pytest precondition** | **Stop `worker` + `bot` containers first** (`docker stop aiwip-worker-1 aiwip-bot-1`) — their blocking Redis `BRPOP` interferes. `pause ≠ stop`. |
| **Enum-deploy gotcha** | api entrypoint uses **`create_all` (not alembic)**. New PG enum values must be **`ALTER TYPE … ADD VALUE`'d into the live `aiwip` DB manually**, then `docker compose build api && docker compose up -d api`. |

---

## 1. Overview — the core loop shape

Single, repeating implement→test→improve→deploy loop. One slice at a time. No batching of backend slices.

```
PLAN (this doc, done)
  └─► per slice:
        Implement ──► Test ──► Review / Improve ──► Deploy ──► Verify-live ──► next slice
        (TDD where a       (gate)     (gate)         (gate)      (gate)
         runner exists)
```

- **Orchestrator** owns: slice sequencing, the approval gate for each backend slice, deploy go/no-go, and the live-verify sign-off. It does not write code.
- **Specialist agents** do the work (implementation-engineer builds; security-reviewer + qa-critic review).
- A slice advances only when its gate passes. On a failed gate → re-dispatch with corrections, never advance.
- **Backend slices** carry two extra mandatory gates: **human approval (before code)** and **security-review (before deploy)**.

### Gate legend

| Gate | Meaning |
|---|---|
| **APPROVAL** | Human approves the backend slice scope **before** implementation begins (Hybrid mode). Frontend-only slices skip this. |
| **TDD/PYTEST** | `api/` change: failing pytest first → implement → green. Run with worker+bot stopped. |
| **TSC/BUILD** | `web/` change: `tsc --noEmit` + `next build` clean. |
| **SECURITY** | `security-reviewer` verdict required for every new public endpoint + every migration / enum change. |
| **QA** | `qa-critic` review gate after substantial slices. |
| **LIVE** | Deploy + browser E2E proof on `:3100` (and live `aiwip` DB for enum/migration slices). |
| **SCOPE** | `git diff --name-only` ⊆ allowed paths; zero `bot/`/`worker/`. |

---

## 2. Agent / skill assignment per phase

| Phase | Owner | When invoked |
|---|---|---|
| Slice scoping + approval gate | **orchestrator** | Start of every backend slice (present scope, get human approval) and frontend-only slices (lighter, no human gate). |
| Implementation (frontend or backend slice) | **implementation-engineer** (`implementation-skill`) | After approval (backend) / after scoping (frontend). One focused slice at a time. |
| Security review | **security-reviewer** (`security-review-skill` → built-in `review-security`) | **Every new/changed public endpoint and every migration / PG-enum change.** Mandatory before deploy of a backend slice. |
| QA review gate | **qa-critic** (read-only) | After substantial slices (8a, 8b) and any slice touching authz/data. Hunts test gaps, fake claims, edge cases. |
| Approval / deploy / live-verify decision | **orchestrator** | Approves scope, makes deploy go/no-go, signs off live-verify, decides next slice. |

Notes:
- Never run two editing agents on the same files concurrently. Slices are serialized.
- security-reviewer and qa-critic are read-only relative to production code; they report, they don't edit.

---

## 3. The 10 gaps → slices, with current status

> Reflects reality on `feat/web-ui-uplift`. Do **not** re-plan shipped work.

### DONE & shipped

| Gap(s) | Slice | Status | Evidence |
|---|---|---|---|
| Phase A — Edit-Candidate + Manual-Sync | Phase A verification | ✅ **DONE** (already built; this was discoverability only) | branch `feat/web-ui-uplift` |
| #5 (drawer visibility) · #3-partial (create/assign labels) · #10 (drawer UX/keyboard) | **Slice 3** — drawer overhaul | ✅ **DONE & shipped** | commits `d88994f`, `1de49eb`, `d4b618c` |
| #8 — Error Recovery | **Slice 4** — toasts + retry | ✅ **DONE & shipped** | commit `48d72e8` |
| #9 — Batch status | **Slice 5** — batch status | ✅ **DONE & shipped** | commit `9c52c32` |
| #1 — Edit Work Item | **Slice 6** — `PATCH /api/work-items/{id}` (audited) | ✅ **DONE, deployed + verified live** | commit `ff3369c` |
| #6 — Mark Duplicate | **Slice 7** — `POST /api/candidates/{id}/duplicate` (audited) | ✅ **DONE, deployed + verified live** | commit `1c2fd26` |

### REMAINING

| Gap(s) | Slice | Type | Status |
|---|---|---|---|
| #4 — Reassign work item | **Slice 8a** | Backend + frontend | ⬜ TODO (next, higher value) |
| #3-rest — Label management | **Slice 8b** | Backend + frontend | ⬜ TODO (after 8a) |
| #5-cards — board cards show assignees/labels (no N+1) | **Slice 8c** | Backend (read enrichment) + frontend | ⬜ TODO |
| Analytics range / drill-down · live-sync polling + relative timestamps · Cmd-K palette · saved views + density toggle | **Frontend backlog (F1–F4)** | Frontend-only | ⬜ TODO (no human approval gate, no security review) |

---

## 4. Remaining slices — the implement→test→improve→deploy loop

**Recommended order:** **8a → 8b → 8c → F1–F4.** 8a (reassign) is highest-value and is kept before 8b.
Frontend-only backlog (F1–F4) can interleave after 8a–8c or be picked up opportunistically; they carry no
approval/security gate.

---

### Slice 8a — Reassign work item (#4) · BACKEND + FRONTEND

**Goal:** edit the assignees of an existing work item from the board drawer.

**New surface:** `PUT /api/work-items/{id}/assignees` · new audit enum value (e.g. `reassigned`) · DB enum migration.

#### Loop

- [ ] **APPROVAL (gate)** — orchestrator presents scope (new PUT endpoint + audit enum value + migration + drawer assignee editor) to human; get explicit go.
- [ ] **Implement — backend (TDD):** write failing pytest for `PUT /api/work-items/{id}/assignees` (happy path + authz + invalid assignee + empty set) → implement endpoint + audit-log write → green. Stop `worker`+`bot` before pytest.
- [ ] **SECURITY (gate):** `security-reviewer` on the new endpoint + the enum migration. Required verdict before any deploy.
- [ ] **Implement — frontend:** drawer assignee editor (add/remove assignees) calling the new endpoint; optimistic update + error toast (reuse Slice 4 pattern). `tsc --noEmit` + `next build` clean.
- [ ] **QA (gate):** `qa-critic` on the full slice — authz coverage, edge cases, no fake claims.
- [ ] **DEPLOY:** `ALTER TYPE … ADD VALUE '<new audit enum>'` into **live `aiwip` DB** (create_all won't add it) → `docker compose build api && docker compose up -d api`.
- [ ] **LIVE (gate):** browser E2E on `:3100` — open a work item, change assignees, confirm persistence + audit entry. Orchestrator signs off.
- [ ] **SCOPE (gate):** `git diff --name-only` ⊆ {`api/`, `core/` (additive), `web/app/**`}; zero `bot/`/`worker/`.

#### Files likely touched

- `api/src/**` — work-items router (new PUT), audit enum, audit-write path. *(additive)*
- `api/tests/**` — new pytest for the endpoint.
- `web/app/board/**` + `web/app/components/**` — drawer assignee editor.
- `web/app/lib/**` — API client method.
- `web/app/assignees/**` — if the assignee picker / source list is reused.

---

### Slice 8b — Label management (#3-rest) · BACKEND + FRONTEND

**Goal:** edit and delete labels, and remove a label from a work item.

**New surface:** `PATCH /api/labels/{id}` · `DELETE /api/labels/{id}` · `DELETE /api/work-items/{id}/labels/{label_id}` · UI.

#### Loop

- [ ] **APPROVAL (gate)** — orchestrator presents scope (three endpoints + label management UI; note DELETE blast radius — cascading effect on work items that use the label) to human; get explicit go.
- [ ] **Implement — backend (TDD):** failing pytest for each endpoint (rename label, delete label incl. in-use behavior, remove label from one work item, authz, not-found) → implement → green. Worker+bot stopped.
- [ ] **SECURITY (gate):** `security-reviewer` on all three endpoints — focus on DELETE authz + cascade / referential-integrity. Required verdict before deploy.
- [ ] **Implement — frontend:** label management UI (rename/delete label; remove-from-item control in drawer); error toasts; `tsc --noEmit` + `next build` clean.
- [ ] **QA (gate):** `qa-critic` — destructive-action edge cases, confirm-before-delete UX, fake-claim check.
- [ ] **DEPLOY:** no enum change expected; if any → live `ALTER TYPE` first. `docker compose build api && docker compose up -d api`.
- [ ] **LIVE (gate):** browser E2E on `:3100` — rename a label, delete a label, remove a label from a work item; confirm persistence. Orchestrator signs off.
- [ ] **SCOPE (gate):** diff ⊆ allowed; zero `bot/`/`worker/`.

#### Files likely touched

- `api/src/**` — labels router (PATCH/DELETE), work-item-labels delete, cascade handling. *(additive)*
- `api/tests/**` — pytest for the three endpoints.
- `web/app/components/**` + `web/app/board/**` — label management UI + drawer control.
- `web/app/lib/**` — API client methods.

---

### Slice 8c — Board cards show assignees + labels, no N+1 (#5-cards) · BACKEND (read enrichment) + FRONTEND

**Goal:** board cards display assignees and labels without a per-card request storm.

**New surface:** enrich the **existing** board endpoint response (additive fields: embedded assignees + labels). No new write endpoint; no migration expected.

#### Loop

- [ ] **APPROVAL (gate)** — orchestrator presents scope (additive response-shape change to board endpoint, single-query enrichment to avoid N+1) to human; get explicit go. *(Public-API response shape changes → still a backend gate.)*
- [ ] **Implement — backend (TDD):** failing pytest asserting cards include assignees + labels in **one** query (guard against N+1 — assert query count or eager-load) → implement eager-load/join → green. Worker+bot stopped.
- [ ] **SECURITY (gate):** `security-reviewer` on the response-shape change (data exposure / over-fetch check).
- [ ] **Implement — frontend:** render assignee avatars + label chips on cards from the enriched payload; drop any per-card fetch. `tsc --noEmit` + `next build` clean.
- [ ] **QA (gate):** `qa-critic` — N+1 actually eliminated, response shape backward-compatible (additive), empty-state coverage.
- [ ] **DEPLOY:** `docker compose build api && docker compose up -d api`.
- [ ] **LIVE (gate):** browser E2E on `:3100` — board renders assignees + labels on cards; verify no per-card request burst (network panel). Orchestrator signs off.
- [ ] **SCOPE (gate):** diff ⊆ allowed; zero `bot/`/`worker/`.

#### Files likely touched

- `api/src/**` — board/read endpoint enrichment (eager-load join). *(additive)*
- `api/tests/**` — N+1 / shape test.
- `web/app/board/**` + `web/app/components/**` — card rendering.
- `web/app/lib/**` — types for enriched payload.

---

### Frontend-only backlog (F1–F4) · `web/app/**` ONLY · no approval/security gate

These touch **no** backend surface. Gates: **TSC/BUILD + LIVE + SCOPE** only (plus light `qa-critic` on the larger ones). No human approval gate, no security review.

| ID | Item | Loop (abbreviated) | Files likely touched |
|---|---|---|---|
| **F1** | Analytics range + drill-down | Implement filters/drill-down → `tsc`+`build` → live-verify on `:3100` → scope check | `web/app/analytics/**`, `web/app/lib/**` |
| **F2** | Live-sync polling + relative timestamps | Implement polling + relative-time formatting → `tsc`+`build` → live-verify → scope check | `web/app/sync/**`, `web/app/components/**`, `web/app/lib/**` |
| **F3** | Cmd-K command palette | Implement palette + actions → `tsc`+`build` → light `qa-critic` (a11y/keyboard) → live-verify → scope check | `web/app/components/**`, `web/app/layout.tsx` |
| **F4** | Saved views + density toggle | Implement persisted view state + density toggle → `tsc`+`build` → live-verify → scope check | `web/app/board/**`, `web/app/components/**`, `web/app/lib/**` |

---

## 5. Definition of Done (per slice) + required evidence

A slice is **Done** only when all applicable items hold and evidence is captured. Orchestrator (not a subagent)
makes the final `complete` call.

### Backend slices (8a, 8b, 8c)

- [ ] **Scope approved** by human before implementation (Hybrid gate).
- [ ] **Tests green** — `.venv/bin/python -m pytest` run with `worker`+`bot` **stopped**; paste the command + pass/fail counts. New endpoints have happy-path + authz + edge-case tests. Anything unrun → `[Not verified]`.
- [ ] **Security verdict** — `security-reviewer` reports **no unresolved CRITICAL/REQUIRED** on every new endpoint + migration/enum. Verdict captured.
- [ ] **QA verdict** — `qa-critic` review with zero unresolved blocking findings.
- [ ] **Enum/migration applied to live DB** — if a PG enum value was added: `ALTER TYPE` executed against live `aiwip` **before** `build api && up -d api` (record the SQL run).
- [ ] **Live E2E proof** — browser action on `:3100` exercised end-to-end; persistence + audit confirmed. Note what was clicked and observed.
- [ ] **Scope-guard diff** — `git diff --name-only` pasted; files ⊆ {`api/`, `core/` additive, `web/app/**`}; **zero `bot/`/`worker/`**.
- [ ] **No fake claims** — `[Implemented]` vs `[Planned]` vs `[Not verified]` separated.

### Frontend-only slices (F1–F4)

- [ ] **`tsc --noEmit` clean** + **`next build` clean** (paste result; unrun → `[Not verified]`).
- [ ] **Live E2E proof** — feature exercised in browser preview on `:3100`.
- [ ] **Scope-guard diff** — diff ⊆ `web/app/**`; zero `bot/`/`worker/`/`api/`/`core/`.
- [ ] **(F3 / larger items)** `qa-critic` a11y/keyboard pass.

---

## 6. Sequencing summary

```
[approved here] → 8a Reassign (#4) → 8b Label mgmt (#3-rest) → 8c Card enrichment (#5-cards)
                        ↑ backend gates: APPROVAL + SECURITY + QA + live-verify on each
                  → F1 Analytics → F2 Live-sync → F3 Cmd-K → F4 Saved views/density
                        ↑ frontend-only: TSC/BUILD + LIVE + SCOPE (no approval/security gate)
```

Stop conditions: any diff touching `bot/` or `worker/`; any backend slice without approval or security verdict;
any "done" claim without the evidence in §5.
