# Stage 8 Report — OpenAI Extraction Pipeline

- **Date:** 2026-06-23 · **Branch:** `build/v1` · **Commit:** `c672f05`

## Goal
Turn context windows into structured Work Item **Candidates** via OpenAI — never WorkItems directly.

## Implemented
- **`llm/`**: `prompts` (PROMPT_VERSION `v1`, precision-first instructions per llm-extraction-spec) +
  Structured-Outputs JSON schema + pydantic validation (`LLMOutput`); `client` (`OpenAIClient` with
  token/cost logging + `FakeLLMClient` for tests).
- **`extract.extract_candidates`**: context → LLM → validated candidates. Confidence bands on `item`:
  `≥0.90 new`, `0.70–0.90 needs_review`, `<0.70 skip`. Links source (`primary`) / supporting / context
  messages; resolves assignees (unresolved → `missing_fields` + `needs_review`); maps priority enum +
  parses due date; logs every call to `ai_runs` (`input_hash`, tokens, cost, status). Invalid
  JSON/schema/API errors are logged and skipped — **never crash** the pipeline. **Never creates WorkItems.**

## Tests Run / Results
- `.venv/bin/python -m pytest` → **68 passed** (7 new, deterministic via `FakeLLMClient`).
- Covered: candidate creation + source/assignee links + `ai_runs`; invalid JSON no-crash; low-confidence
  skip (still logged); needs_review band; invalid priority→null + due null; unresolved assignee →
  missing_fields + needs_review; due-date parse; **no WorkItems created**.
- **LIVE verified (gpt-4o-mini, real key):**
  - Real chat (42 casual messages) → **0 candidates** + `ai_run success` (1568+28 tok, $0.00025) —
    correct precision: no false tasks from chatter.
  - Synthetic work message → **1 task**, `status=new`, `priority=critical`, **due 2026-06-26 (Friday,
    correctly resolved from "до пятницы")**, assignee resolved, `item_confidence=1.0`. (Demo data cleaned up.)

## Decisions Made
- Structured Outputs (strict JSON schema) for guaranteed-valid responses; `temperature=0`.
- Confidence-band cutoffs are the main precision lever (tunable in the eval phase, Stage 12).
- `prompt_version` stored on every `ai_run` and candidate for attribution.

## Files Changed
`worker/src/aiwip_worker/llm/{__init__,schema,prompts,client}.py`, `worker/src/aiwip_worker/extract.py`,
`worker/tests/test_extract.py`, `worker/pyproject.toml` (+`openai`).

## Next Recommended Stage
**Stage 9 — Candidate Review** (list/detail/edit/approve/reject API; approve → WorkItem; audit on
actions) + **Stage 10** (WorkItem/board) + **Stage 11** (audit). Backend testable now; review/board **UI**
in the consolidated front-end pass.

## Proceed / Do Not Proceed
**PROCEED to Stage 9.** The AI core works live end-to-end (68 tests + real extraction with correct
precision and a correct positive extraction).
