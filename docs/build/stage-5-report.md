# Stage 5 Report — Message Normalization

- **Date:** 2026-06-23 · **Branch:** `build/v1` · **Commit:** `371eccf`

## Goal
Convert stored messages into normalized content; register attachments as placeholders; update
`processing_status`; ensure unsupported files don't break processing.

## Implemented
- **Connector/sync:** `FetchedAttachment` + `message_type`/`attachments` on `FetchedMessage`; Telegram
  best-effort media detection (metadata only — no download); sync stores `message_type` and creates
  `message_attachments` rows.
- **`aiwip_worker.normalize`:** `clean_text` (collapse whitespace, drop blank lines); `normalize_message`
  (sets `normalized_content`; registers supported attachments — image/voice + pdf/docx/xlsx/pptx — as
  `new` placeholders; marks unsupported attachments `skipped`; sets message `processing_status`
  `normalized`/`skipped`); `normalize_pending` batch (failures marked `failed`, never crash the batch).
- **Pipeline:** the consumer now runs `sync → normalize` per job.

## Tests Run / Results
- `.venv/bin/python -m pytest` → **48 passed** vs real Postgres + Redis.
- Stage 5 (`test_normalize.py`, 6): text cleaned/normalized; empty → skipped; image attachment registered;
  unsupported document → attachment `skipped` + message `skipped` (no crash); supported pdf → normalized;
  batch normalize.
- **Live on real data:** normalized the **41 synced messages** → **26 normalized** (text) + **15 skipped**
  (media-only/empty) — unsupported/empty handled cleanly.

## Not Implemented (intentional — system-spec §9/§10, deferred)
- Media *intelligence*: OCR/vision (image), document text extraction (pdf/docx/xlsx/pptx), voice
  transcription. Attachments are **registered placeholders** only; extraction is a later stage.

## Decisions Made
- Supported-attachment set: image/voice always registered (future OCR/vision/transcription); documents
  supported only for pdf/docx/xlsx/pptx mimes; everything else → `skipped` (registered, not processed).

## Files Changed
`worker/src/aiwip_worker/{connectors/base.py,connectors/telegram.py,sync.py,normalize.py,consumer.py}`,
`worker/tests/test_normalize.py`.

## Docker check (this session)
- Stack is **up & healthy** (5 services); fixed the api entrypoint bug (claimed to migrate, only ran
  uvicorn) → now `create_all` ensures schema; applied schema to the running Docker Postgres (19 tables).
  `scripts/entrypoint-api.sh` edited (left in the working tree with the user's infra files, uncommitted).
- ⚠️ **Port conflict:** brew Postgres/Redis (127.0.0.1) and Docker (IPv6 `*`) both bind 5432/6379.
  Host clients (psycopg) resolve to brew; Docker uses its own network. Recommend running **one** stack:
  `brew services stop postgresql@16 redis` to go Docker-only (then create test DBs + re-sync into Docker),
  or stop the Docker stack to stay on brew. The 41 messages currently live in **brew**.

## Next Recommended Stage
**Stage 6 — Assignee Management** (assignee CRUD API + resolver foundation; admin-only). No external creds.
Then 7 (context builder) → **8 (OpenAI candidates — needs `OPENAI_API_KEY`)**.

## Proceed / Do Not Proceed
**PROCEED to Stage 6.** Normalization is complete and verified on real data (48 tests).
