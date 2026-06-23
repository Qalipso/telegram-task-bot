# Stage 7 Report — Context Builder

- **Date:** 2026-06-23 · **Branch:** `build/v1` · **Commit:** `dfff717`

## Goal
Assemble useful analysis windows from stored messages, to feed the AI pipeline.

## Implemented
- **`aiwip_worker.context.build_context`** (returns a `ContextWindow` dataclass, logged for the pipeline):
  - last ~20 **content** messages for the chat (configurable `window`);
  - **reply-referenced** messages pulled in (reply chains) — connector now captures `reply_to_msg_id`
    into `raw_payload`;
  - **time-gap topic segmentation** (`topic_gap_minutes`, default 60): the recent contiguous run only,
    so a new topic doesn't pollute the previous one;
  - sender metadata + **UTC** timestamps;
  - heuristic `summary` + `confidence` (the LLM produces the authoritative ones in Stage 8).

## Tests Run / Results
- `.venv/bin/python -m pytest` → **61 passed** vs Docker Postgres + Redis.
- Stage 7 (`test_context.py`, 5): last-20 window; new-topic split (pre-gap excluded); topic continuation;
  reply-chain pulls referenced message; confidence in `[0,1]` and grows with a larger coherent window.
- **Live on the real chat:** window=1, confidence=0.14 — the chat's messages are >60 min apart, so
  segmentation correctly isolates the latest message and honestly reports low confidence. `topic_gap_minutes`
  is the tuning knob for the eval phase.

## Decisions Made (per implementation-plan §5)
- **Fixed window + reply chains + a simple time-gap heuristic — NO ML segmentation** for MVP. Revisit only
  if eval shows the fixed window is the bottleneck.
- Reply info stored in `messages.raw_payload` (no schema change); existing messages synced before this
  change have no reply data until re-pulled.

## Files Changed
`worker/src/aiwip_worker/{context.py,connectors/telegram.py}`, `worker/tests/test_context.py`.

## Next Recommended Stage
**Stage 8 — OpenAI Extraction Pipeline** (context window → structured candidates via Structured Outputs;
classify → extract → resolvers (assignee/priority/due) → `ai_runs` logging + `prompt_version`). **⚠️ Needs
`OPENAI_API_KEY` in `.env` (still empty) for the live run.** Can be built + tested mock-first and wired
live the moment the key is added.

## Proceed / Do Not Proceed
**PROCEED to Stage 8** (build mock-first; live run gated on `OPENAI_API_KEY`). Context builder complete
and verified (61 tests).
