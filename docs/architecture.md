# Technical Architecture Overview

> Document 3 of the **AI Work Intelligence Platform** documentation set.
> This is the canonical English version (`architecture.md`); a maintained Russian copy is kept in `architecture.ru.md`.

## High Level Architecture

```text
Telegram Connector
→ Sync Layer
→ Content Normalization
→ Context Builder
→ AI Analysis Pipeline
→ Candidate Review
→ Work Management Layer
```

## Connector Layer

Responsible for retrieving data.

The `Connector` interface:

- `fetchMessages()`
- `fetchMedia()`
- `fetchMetadata()`

MVP: `TelegramConnector`.

## Sync Layer

Runs on a schedule and manually. Responsible for:

- retrieving new messages
- persisting sync state
- preventing re-reading

## Content Normalization Layer

Converts the various data types into a single format:

- Text → Text
- Voice → Transcript
- Image → OCR + Vision Description
- PDF → Extracted Text
- DOCX → Extracted Text
- XLSX → Extracted Text
- PPTX → Extracted Text

Result: **Normalized Content**.

> **Voice is not transcribed automatically.** The `Voice → Transcript` mapping applies only after an
> admin manually triggers transcription (`voice.transcribe_manual`) — see `system-spec.md` §9.

## Context Builder

Builds the analysis window. Rules:

- Use messages stored in the database.
- Use the most recent messages in the context.
- If a continuation of a discussion is detected, extend the context backward.
- If a new topic is detected, start a new context.

## AI Analysis Pipeline

Stages:

1. Classification
2. Entity Extraction
3. Assignee Resolution
4. Priority Resolution
5. Due Date Resolution
6. Confidence Scoring
7. Candidate Generation

## Review Layer

All candidates require confirmation. Possible actions: **Approve / Reject / Edit**. After
confirmation, a WorkItem is created.

## Work Management Layer

Kanban Board. Statuses:

- Inbox
- Backlog
- Ready
- In Progress
- Blocked
- Review
- Done
- Cancelled
- Archived

## Evaluation Layer

Each Candidate can participate in a dataset. The following are stored:

- Prompt
- Model
- Response
- Cost
- Tokens
- Expected Result
- Actual Result
- Evaluation Result

## Audit Layer

Logs: Sync Events, Approvals, Rejections, Status Changes, Manual Updates, User Actions.

## Deployment

- Frontend: Next.js
- Backend: FastAPI
- Database: PostgreSQL
- Queue: Redis
- Workers: Python
- Containerization: Docker

---

## Core Flows

> Carried over from the previous design spec; aligned with the new model (Candidate → WorkItem).

### Flow 1 — Automatic synchronization
```text
Scheduler enqueues a sync job (trigger=scheduled)
  → Worker reads sync_state.last_external_message_id for the chat
  → Telegram Connector fetches messages with id > last_external_message_id (in batches)
  → new messages are persisted to messages (idempotent on chat_id+external_message_id)
  → Content Normalization converts messages to normalized_content
  → Context Builder assembles analysis windows
  → AI Analysis Pipeline creates Candidates
  → sync_state is updated; sync_run is finalized
```

### Flow 2 — Manual synchronization
```text
User clicks Sync Now → backend enqueues a sync job (trigger=manual)
  → UI polls status → worker performs the read/analysis
  → dashboard refreshes on completion
```

### Flow 3 — Candidate review
```text
Admin opens Candidates → sees the detected items
  → edits fields as needed → approve / reject
  → an approved candidate becomes a WorkItem (status=inbox)
```

### Flow 4 — Assignee management
```text
Admin opens Assignees → adds/edits a person
  → sets Telegram ID, username, aliases → deactivates if needed
  → the resolver uses the active list on the next analysis
```

---

## Non-functional requirements

> Carried over from the previous design spec.

**Reliability:** sync must not break the whole system; errors are logged and visible; partial sync is
visible (`partial_success`); re-running does not create duplicates.

**Security:** UI access is restricted to authorized users only (email + password + session);
the Telegram session / API keys and the LLM API key are stored in env / a secret store (`credentials_ref`),
never in code; raw messages are not exposed externally without authorization.

**Performance:** sync processes messages in batches; LLM calls are throttled (Batches API,
prompt caching, the `processing_status` gate); re-analyzing already-processed messages is unnecessary.

**Audit:** retain sync history (`sync_runs`); the source of every item (`candidate_messages`);
changes via `audit_logs` (before/after).

---

## Repository layout (proposed)

> Carried over from the previous design spec.

```text
telegram-task-bot/
├── docs/                  ← documentation set (this file and others, EN + RU)
├── docker-compose.yml
├── .env.example           ← documents required secrets (no real values)
├── worker/   (Python)     ← Telethon connector, sync worker, normalization, context builder,
│   ├── src/                  AI pipeline, resolvers, LLM client, SQLAlchemy models
│   └── tests/
├── api/      (FastAPI)    ← REST endpoints, shared models with the worker
│   ├── src/
│   └── tests/
└── web/      (Next.js)    ← UI: dashboard, candidates, kanban, assignees, sync history
    └── ...
```
