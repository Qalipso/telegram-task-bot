# Reconciliation Report

> Document of the **AI Work Intelligence Platform** documentation set.
> Canonical English (`reconciliation.md`); Russian copy at `reconciliation.ru.md`.

## Purpose & precedence

This report records the cross-document inconsistencies found by an automated audit of the doc set
(5 dimensions, **40 findings, each adversarially verified** to filter misreads) and gives a single
resolution for each.

**Precedence rule:** where any document conflicts with another, **`system-spec.md` (v1.0,
Approved) governs**, and this report's resolution is authoritative for anything v1.0 does not
settle. The 7 sub-docs are detailed companions; this report + v1.0 are the source of truth.

Status legend: **Resolved by v1.0** (apply the listed doc fix) · **Decision (D11–D25)** (needs
ratification; recommended resolution given) · **Test gap** (add test cases) · **Cleanup** (wording
alignment).

---

## 1. Critical (3) — resolved by v1.0

| ID | Issue | Resolution |
|----|-------|------------|
| `enums-candidate-type-members-diverge` | Candidate type set differs (Domain Model omits `knowledge`; DB adds `decision_future`/`risk_future`; LLM uses `decision`/`risk`). | **v1.0 §6 governs:** active types = `task, request, reminder, idea, knowledge`; future = `decision, risk`. **Fix applied:** Domain Model now lists all 5 active types. Future-type token naming → **D11**. |
| `enums-candidate-status-domain-vs-db` | Domain Model has 4 candidate statuses; DB/LLM/tests use 7 (incl. `needs_review`, `duplicate`, `error`). | **v1.0 §13 governs:** `new, needs_review, edited, approved, rejected, duplicate, error`. **Fix applied:** Domain Model now lists all 7, with one-line semantics for `needs_review`/`duplicate`/`error`. |
| `pipeline-test-coverage-voice-transcription-normalization-contradiction` | Architecture normalizes Voice→Transcript automatically; tests (20–21) require manual admin trigger. | **v1.0 §9/§10 governs:** voice is **not** auto-transcribed; admin triggers it. **Fix applied:** Architecture Content-Normalization section now states the Voice→Transcript mapping applies only after the manual `voice.transcribe_manual` step. |

## 2. Resolved by v1.0 (apply doc alignment)

| ID | Resolution |
|----|------------|
| `entity-table-field-workitem-reasoning-missing-column` | v1.0 §6: WorkItem has **Reasoning**. Add `reasoning` to `work_items`, snapshotted from the candidate at approval. |
| `entity-table-field-workitem-confidence-missing-column` | v1.0 §6: WorkItem has **Confidence**. Add `confidence` to `work_items` (snapshot at approval). |
| `entity-table-field-workitem-source-messages-no-join` | WorkItem **Source Messages** is derived via `work_items.source_candidate_id → candidate_messages` (the candidate is the immutable snapshot). Documented; no extra table for MVP → see **D16** if denormalization is wanted. |
| `entity-table-field-candidate-type-enum-mismatch` | Same as the critical type finding — Domain Model aligned to the 5 active types. |
| `entity-table-field-candidate-status-enum-mismatch` | Same as the critical status finding — Domain Model aligned to the 7 statuses. |
| `enums-human-feedback-vs-candidate-status` | `approved`/`rejected`/`edited_then_approved` are **evaluation-dataset labels** (Evaluation Plan + LLM Human Feedback Loop + D10), **not** `candidate.status`. An edited-then-approved candidate ends at `status=approved`; the edit is recorded via the `candidate_edited` audit action. |
| `enums-audit-actions-three-way-mismatch` | The DB `audit_logs` action list (9 tokens) is **canonical** (v1.0 §18). Domain Model / Architecture wording aligns to it; the undefined "User Actions" bucket is dropped. Missing tests → Test gap below. |
| `enums-evaluation-result-missing-pending` | DB enum `pass/fail/partial/pending` is canonical. Domain Model `EvaluationCase.result` references it; "pending" = not-yet-run. Report math excludes `pending` from rates. |
| `enums-work-item-vs-candidate-type-knowledge-only` | Not a break: `decision_future`/`risk_future` are **inactive reserved** enum slots (LLM spec never emits them). For all active types, candidate→work_item promotion is type-preserving. Ties to **D11**. |
| `pipeline-test-coverage-context-window-size-exact-vs-approx` | v1.0 §11 governs: **base window = 20 messages**. Standardize on "20" across docs (drop the "~20" / "up to 20" variants). |
| `gaps-security-attachment-storage-backend-undefined` | v1.0 §23: **local file storage** for MVP. `message_attachments.storage_path` = path under a configured local directory; S3 deferred. |

## 3. New decisions to ratify (D11–D25)

> These are genuine design gaps v1.0 does not settle. **Ratified (Accepted) 2026-06-23** with the
> resolutions below; recorded in `decisions.md`.

| ID | Question | Recommended resolution |
|----|----------|------------------------|
| **D11** | Future-type token: `decision_future`/`risk_future` (DB) vs `decision`/`risk` (LLM/v1.0)? | Use **`decision`/`risk`** everywhere; mark them reserved/inactive in the DB enum comment (drop `_future`). |
| **D12** | Where do feedback outcomes live? | Eval-dataset labels (not `candidate.status`); `was_edited` derivable from the `candidate_edited` audit row. |
| **D13** | `attachment_type` has both `image` and `photo`. | Collapse to **`image`** (matches `message_type`); drop `photo`. |
| **D14** | `sync_runs.trigger_type='retry'` has no producing flow. | Keep `retry`; add a one-line flow: admin re-runs a `failed` sync_run → new `sync_run` with `trigger_type='retry'`. |
| **D15** | `message_attachments.processing_status` enum undefined. | Define `new, processing, processed, failed, skipped`. |
| **D16** | WorkItem source messages: derive vs denormalize? | **Derive** via `source_candidate_id → candidate_messages` for MVP (no `work_item_messages` table). Revisit if candidates become mutable post-approval. |
| **D17** | LLM `missing_fields` has no storage. | Add `missing_fields jsonb` (or `text[]`) to `candidates`. |
| **D18** | `confidence.item` (LLM) vs `task_confidence` (DB) naming. | Keep DB `task_confidence`; document the explicit mapping `confidence.item → task_confidence` in the LLM spec. |
| **D19** | `confidence.assignee` (scalar) vs `candidate_assignees.confidence` (per-row). | `confidence.assignee` = overall assignee-resolution confidence (stored on `candidates`); `candidate_assignees.confidence` = per-candidate-assignee score. Both kept, distinct semantics. |
| **D20** | Root `context_summary`/`context_confidence` storage. | `context_confidence` → `candidates.context_confidence` (exists); `context_summary` → store per analyzed context window (add column on `candidates` for MVP, snapshotted). |
| **D21** | `connector_accounts.credentials_ref` format. | A reference (not the secret) — env var name or secret-manager key; the secret lives outside source/DB (v1.0 §22). Define the ref format in DB design. |
| **D22** | `audit_logs.entity_type` allowed values. | Enumerate: `candidate, work_item, assignee, chat, sync_run, message`. |
| **D23** | `ai_runs.input_hash` idempotency/retry. | `input_hash` dedupes identical AI calls (skip/return cached on match); queue retry = 3× exponential backoff + dead-letter (v1.0 §21). |
| **D24** | `assignees.user_id ↔ users` relationship. | FK → `users.id`, **nullable** (an assignee need not be a system login); one user ↔ at most one assignee. |
| **D25** | Candidate→WorkItem assignee promotion. | On approval, copy `candidate_assignees` → `work_item_assignees` (carry `is_primary`; drop per-row `confidence`). |

Also open (lower urgency): a `labels` master table vs free-text tags — v1.0 §19 lists only the
`candidate_labels`/`work_item_labels` join tables. **Recommended:** a small `labels` master
(`id, name, color?`) referenced by both joins, so the tag vocabulary is controlled. Flagged for
confirmation.

## 4. Test-coverage gaps (add to Test Plan)

| ID | Add |
|----|-----|
| `pipeline-test-coverage-connector-fetchmedia-metadata-untested` | Tests for `Connector.fetchMedia()` and `fetchMetadata()`. |
| `pipeline-test-coverage-entity-extraction-stage-untested` | Test for AI stage 2 (title/summary generation quality). |
| `enums-audit-actions-three-way-mismatch` (tests) | Audit tests for `candidate_created`, `assignee_created`, `assignee_updated`. |
| `enums-evaluation-result-missing-pending` (tests) | Test for a `pending` (not-yet-run) evaluation case + how the report counts it. |

## 5. Minor cleanups (wording alignment, no decision needed)

| ID | Note |
|----|------|
| `entity-table-field-syncrun-fields-naming-drift` | Domain Model `SyncRun` fields are conceptual; DB `sync_runs` columns (`messages_read/saved/failed`, `candidates_created`) are canonical. |
| `entity-table-field-evaluationcase-input-field-mapping` / `gaps-security-evaluationcase-fields-vs-table-divergence` | Unify `EvaluationCase` (Domain Model) ↔ `evaluation_cases` (DB) ↔ Evaluation Plan dataset structure into one field set; DB columns canonical. |
| `llm-db-mapping-2-buckets-vs-3-roles` / `gaps-security-context-role-no-llm-output-field` | LLM emits `source_message_ids` + `supporting_message_ids`; the Context Builder populates `candidate_messages.role='context'` rows (context-window messages, not LLM-emitted). Mapping: source→`primary`, supporting→`supporting`, builder→`context`. |
| `llm-db-mapping-root-context-summary-storage` | See D20. |
| `pipeline-test-coverage-image-normalization-mapping-mismatch` | Standardize image normalization wording to "OCR text + vision summary" across docs. |
| `enums-sync-trigger-vs-flows` | See D14. |
| `enums-attachment-processing-status-undefined` | See D15. |

---

## Summary

- **Critical:** 3 — all resolved by v1.0; fixes applied to Domain Model and Architecture.
- **Resolved by v1.0:** 11 alignment items.
- **New decisions (D11–D25 + labels master):** 16 — **ratified 2026-06-23**, recorded in `decisions.md`.
- **Test gaps:** 4 sets of cases to add.
- **Minor cleanups:** 6 wording alignments.

Rejected by adversarial verification: 0 (all 40 findings confirmed real or partial).
