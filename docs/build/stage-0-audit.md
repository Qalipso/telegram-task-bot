# Stage 0 Report — Documentation & Planning Audit

- **Date:** 2026-06-23
- **Role:** Implementation Orchestrator (per the Master Implementation Orchestrator Prompt)
- **Status:** Audit complete. **Coding NOT started.** Build scope awaiting ratification (see §8).
- **Inputs read (canonical EN, 12 docs):** `product-brief`, `system-spec` (v1.0, Approved — authoritative),
  `domain-model`, `architecture`, `database-design`, `llm-extraction-spec`, `evaluation-plan`,
  `test-plan` (110 cases), `decisions` (D1–D25), `reconciliation` (40 findings), `implementation-plan`
  (v1.1, senior-panel-reviewed), `README`.

---

## 1. Headline

The doc set is unusually complete and **already internally consistent**: `reconciliation.md` records a
40-finding cross-document audit (all adversarially verified, 0 rejected) and `decisions.md` ratifies
D1–D25 plus a `labels` master table on 2026-06-23. There are **no remaining doc-vs-doc contradictions**
to resolve before building.

There is, however, **one unratified scope fork** that determines the size and sequence of the entire
build (§3). It is the only thing blocking Stage 1.

**No code exists yet** (`find` for `*.py/*.ts/docker-compose` returns nothing). We are genuinely at zero.

---

## 2. Precedence (from reconciliation.md)

`system-spec.md` v1.0 (**Approved**) governs. `reconciliation.md` + D1–D25 are authoritative for anything
v1.0 leaves open. `implementation-plan.md` is **"Draft for executive approval" — NOT yet ratified**; it
is a strong senior-engineering recommendation, not binding. This matters: by current precedence the
**full v1.0 scope is authoritative**, and the leaner plan is a proposal awaiting your sign-off.

---

## 3. The one decision that gates the build — Full v1.0 vs Lean MVP

The Master Orchestrator Prompt's "MVP Must Include" list mirrors **system-spec v1.0 §25 (Definition of
Done)**. The team's own `implementation-plan.md` v1.1 argues that list "**is not an MVP — it is a v1
product**," and recommends a drastically smaller text-only vertical slice. These genuinely conflict.
Both defer multimodal (OCR/vision/voice/doc), so that is **not** in dispute. The live deltas:

| Topic | Full v1.0 / Master Prompt (authoritative today) | Lean MVP (`implementation-plan.md` v1.1, unratified) |
|---|---|---|
| Queue | Redis (system-spec §21, §23) | **Drop Redis** → in-process scheduler + Postgres `jobs` table (durable retries/DLQ) |
| Tables | ~17–19 (DB design) | **~11**; defer `message_attachments`, `labels`, `candidate_labels`, `work_item_labels`, `evaluation_cases` |
| Kanban statuses | **9** (`inbox…archived`; test #71) | **4** (`inbox / in_progress / done / cancelled`) |
| Tags | In MVP (system-spec §15) | **Defer** (Could-Have) |
| Multi-assignee | In MVP (tests #60, #69) | **Defer**; single assignee |
| Assignee role | In MVP (tests #76, #87–89) | **Should-Have**; MVP is single-admin (no notifications → assignee has no trigger to log in) |
| Connector abstraction | Interface for 5 sources | Build Telegram **concretely** (YAGNI) |
| Accuracy targets | **≥90% / ≥80% as MVP acceptance** (product-brief, system-spec, evaluation-plan "Success Criteria") | **North-stars, not gates**; gate on reviewer behavior + precision proxy (flagged for exec sign-off) |
| Timeline (3-person team) | ~4–6 months to first pilot | **~10–16 weeks** to a validated single-admin MVP |

**Orchestrator's recommendation:** **Lean MVP spine + full schema kept (Hybrid).** Rationale — the Master
Prompt's own optimization targets (§13: working software, testability, low false positives, reliable
release path) and Rule 2 (thin vertical slices) point at the lean spine. But re-migrating a database is
expensive, so define the **full schema/migrations up front** (cheap now) while implementing only lean
*behavior* (4-status board, single assignee, no Redis). This is presented as Option C in the decision
below; the leanest (Option A) and the full v1.0 (Option B) are the alternatives.

---

## 4. MVP Cut (recommended — pending §8 ratification)

| Tier | Items |
|---|---|
| **Must Have** | One-chat Telegram **text** sync (manual + scheduled); idempotent storage (`chat_id+external_message_id`); context builder (fixed 20-msg window + reply/quote chains); classify→extract → candidates (Structured Outputs); per-field confidence; assignee resolution from a managed list; review queue (approve/edit/reject) with low-confidence + missing-field highlighting; work items + minimal board; `audit_logs`; `ai_runs` logging + `prompt_version`; offline eval harness + seed set; email+password auth + roles; Docker Compose. |
| **Should Have** | Due-date + priority resolution (launchable low-confidence); sync-history screen; dashboard counts; scheduled (6h) sync. |
| **Could Have** | Tags; full 9-status Kanban; multi-assignee; evaluation UI/reports; assignee-facing views; multi-chat. |
| **Not Needed Yet** | Voice transcription; image/OCR + document/vision normalization; connector abstraction (Slack/Email/WhatsApp/Discord); decision/risk types; notifications; multi-tenancy; calendar/working-day awareness. |

---

## 5. Implementation Sequence (recommended) & Dependency Graph

Critical path (everything else hangs off this spine):

```text
Foundation (repo, Docker, Postgres, auth/roles, health, CI baseline)
  → DB schema + migrations (full schema; Alembic)
  → Core storage + sync_state/sync_runs + manual POST /sync/run
  → Telegram connector (Telethon, mockable interface) + incremental fetch + dedup
  → Message normalization (text; attachment registration as no-op placeholders)
  → Assignee management (CRUD + resolver foundation)
  → Context builder (fixed 20-msg window + reply/quote chains)        ← HIGH RISK gate
  → AI pipeline (classify → extract via Structured Outputs → resolvers → ai_runs)  ← CRITICAL
  → Candidate review UI (approve/edit/reject + audit)
  → Work items + minimal board (assignee promotion D25)
  → Audit logging (cross-cutting; landed incrementally per stage)
  → Evaluation foundation (offline harness + seed set, parallelizable from AI stage)
  → E2E + QA hardening + release package
```

Maps onto the Master Prompt's Stages 1–15. Stages run as controlled loops with a stage report and a
Proceed / Do-Not-Proceed gate after each (template in the Master Prompt §7). Eval-harness scaffold can
be built in parallel with the AI pipeline.

---

## 6. Risk Register (top risks, carried + sharpened from implementation-plan §9)

| # | Risk | Impact | Prob | Mitigation |
|---|---|---|---|---|
| R1 | AI task-detection quality below useful bar (RU chat, low task base-rate) | Critical | High | Human-in-loop safety net; classify-then-extract; eval-driven prompt iteration; gate on reviewer behavior, not a 90% number |
| R2 | Telegram user-session ban / ToS / auth ops — **no history-capable fallback** (Bot API can't read prior/group history) | Critical | Med | Dedicated account, conservative rate limits, secure session storage, re-auth runbook; **week-0 spike** + written pilot consent before depending on live sync |
| R3 | No task-level (semantic) dedup — only message-level uniqueness | High | High | Deterministic guard: suppress candidates whose `source_message_ids` substantially overlap a live candidate/work-item for the chat; mark `duplicate` |
| R4 | Due-date extraction errors (relative dates, TZ) | High | High | UTC anchoring; low-confidence highlight; always human-confirmed; eval cases for relative dates |
| R5 | Context-window failures (wrong/mixed topic) | High | Med | Fixed window + reply chains for MVP; eval the window; defer smart segmentation |
| R6 | MVP over-scope → never ships | High | High | Cut to text-only spine; time-box pilot (this is what §3 decides) |
| R7 | Durable retries/partial-failure if Redis dropped | Med | Med | Postgres `jobs` table (`status, attempt_count, locked_at`) + "failed runs" view as DLQ |
| R8 | Prompt drift / unattributable regressions | Med | Med | `prompt_version` in `ai_runs` + eval before every prompt/model change |
| R9 | Two-language stack (TS+Py) drag for a small team | Med | Med | Thin FastAPI↔worker contract; one owner per stack |

---

## 7. Verification & integration strategy (proposed)

To keep every stage **test-verifiable now** (Iron Law 3: no completion claim without fresh evidence),
the Telegram connector and OpenAI client are built behind **interfaces with mock/fixture
implementations** by default. This lets Stages 4–8 produce real test evidence without live credentials,
and isolates the two external-dependency risks (R1, R2) into a dedicated week-0 spike before we depend
on live sync. Live wiring happens when credentials + a consenting pilot chat exist. (See decision §8-Q2.)

---

## 8. Open Decisions — RATIFIED 2026-06-23

- **Q1 — Build scope: FULL v1.0** (master-prompt / system-spec DoD). Redis queue, full ~17–19-table
  schema, tags, 9-status Kanban, multi-assignee, Assignee role, all 16 stages as written. §3–§5 above
  describe the *lean* recommendation that was **not** chosen; the build follows full scope.
- **Q2 — Integration: LIVE from day one.** Real Telethon + OpenAI wired. Mocked-data tests still
  authored (Test Plan mandates them), and a week-0 Telethon-survivability + RU-quality spike still
  precedes reliance on live sync (R2). Live creds required from the user before Stage 4 / Stage 8.
- **Q3 — Accuracy targets: NORTH-STARS.** 90/80 are eval-set targets; release gates on reviewer
  behavior + precision proxy `approved/(approved+rejected)`. (Resolves the evaluation-plan "Success
  Criteria" tension; treat as the exec-ratified amendment the implementation-plan flagged.)

**Net effect on the build:** maximal scope, minimal release-gating on raw accuracy. Schema, infra
(Redis included), and stage list follow full v1.0; the MVP-cut table in §4 is superseded by full scope.

## 9. Lower-priority open questions (resolve before the stage that needs them)

- First pilot customer + written consent for a Telegram **user account** reading their chat (before Stage 4 live).
- RU as primary chat language → eval seed set weighting (≥40 RU / 20 EN) (before Stage 12).
- Initial-admin bootstrap, password reset, session expiry, login rate-limiting (before Stage 3 hardening).
- Handling of forwarded / edited / deleted / system / bot messages (before Stage 5).
- Work-item editability post-creation & status-change permissions (before Stage 10).

---

## 10. Acceptance (Stage 0)

- [x] All docs read; precedence established.
- [x] Doc-vs-doc contradictions: none remaining (reconciled 2026-06-23).
- [x] Scope fork identified and quantified (§3).
- [x] MVP cut, implementation sequence, dependency graph, risk register produced.
- [x] Open decisions + open questions listed.
- [x] **Build scope ratified (Q1–Q3): Full v1.0 / Live / North-stars (2026-06-23).**

**Proceed / Do Not Proceed:** **PROCEED** to Stage 1 (Project Foundation) under full v1.0 scope.
