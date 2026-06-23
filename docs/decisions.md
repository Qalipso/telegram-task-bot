# Design Decisions (D1–D25)

> Document from the **AI Work Intelligence Platform** documentation set.
> This is the canonical English version (`decisions.md`); a maintained Russian copy exists (`decisions.ru.md`).
>
> **Status:** D1–D10 confirmed; **D11–D25 + the labels master ratified (Accepted) 2026-06-23**
> (resolutions from the reconciliation report; reflected in the Database Design and LLM Extraction Spec).
>
> **Merged from the former design spec** "2026-06-23 Telegram Task Recognition Bot Design", which
> has been retired (merge then retire). This document captures the decisions and their current status
> relative to the new AI Work Intelligence Platform model.

| ID | Question | Decision / status |
|----|----------|-------------------|
| D1 | API owner | **Current.** FastAPI owns the data/LLM logic (SQLAlchemy models shared with the worker); Next.js is UI + a thin proxy. |
| D2 | Backfill scope on first sync | **Current.** Configurable `initial_lookback` (the last N days), not the entire history. |
| D3 | LLM model tier | **Current.** AI provider = **OpenAI models** (per system-spec v1.0 §3 and §22); the earlier `claude-opus-4-8` default is reversed. A cheaper tier is a config lever (`model_name` in `ai_runs`), with no automatic downgrade. |
| D4 | Timezone and work week | **Current.** UTC, Mon–Fri (overridable). The LLM Extraction Spec confirms: current time is in UTC. |
| D5 | UI authorization | **Current.** Email + password + server-side session; aligned with `users.role` (`admin`/`assignee`). |
| D6 | Audit depth | **CANCELLED / expanded.** The former "`updated_at` only" was replaced by a full `audit_logs` table (with `before_value`/`after_value`) — see Database Design. |
| D7 | Documentation language | **Current.** Both languages; **EN is canonical** (`*.md`), RU is a maintained copy (`*.ru.md`). |
| D8 | Context window | **Clarified.** Reply chain + quoted messages + **the last ~20 messages** from the DB (per the LLM Extraction Spec); do not mix different topics; extend backward when a topic continues. (The former "N=10 / 60 min" variant was replaced by the value "20" from the current LLM spec.) |
| D9 | Multi-message tasks | **Confirmed and implemented in the schema.** Window (chunk) analysis; the candidate is linked to messages via `candidate_messages.role` (`primary` = anchor, `context`, `supporting`). The dedup invariant is the uniqueness of `chat_id + external_message_id` at the `messages` level; one approved candidate → one `work_item`. |
| D10 | Feedback loop | **Current, formalized.** Approve / Reject / Edited-then-Approved → Evaluation Dataset; see the LLM Extraction Spec (Human Feedback Loop) and the Evaluation Plan. |

## Resolved during reconciliation (2026-06-23)

- **Voice transcription:** resolved — voice is **not** transcribed automatically; only after a manual
  admin action (`voice.transcribe_manual`). Applied to the Architecture Content Normalization section
  and system-spec §9.
- **Confidence fields:** resolved by **D18** — keep `task_confidence` in the DB; map the LLM
  `confidence.item → task_confidence` in the LLM Extraction Spec.
- The full 40-finding audit and its resolutions are in the reconciliation report (`reconciliation.md`).

## New decisions (D11–D25)

> **Status: Accepted (ratified 2026-06-23).** These design gaps `system-spec.md` v1.0 does not settle
> were carried over from the reconciliation report (§3) and ratified as the resolutions below; they are
> reflected in the Database Design and LLM Extraction Spec.

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

Also ratified: a `labels` master table (`id, name, color?`) referenced by `candidate_labels` and
`work_item_labels`, so the tag vocabulary is controlled (rather than free-text). Added to the
Database Design.
