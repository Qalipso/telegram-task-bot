# Integrating with Other Systems

How to extend and integrate the AI Work Intelligence Platform (aiwip): adding inbound message sources,
configuring or swapping the AI provider, driving the REST API from external systems, reading the data
stores directly, and where outbound/notification integrations would hook in. For running the system,
see [`RUNNING.md`](RUNNING.md).

---

## 1. Inbound message sources — the Connector interface

The single extension point for new message sources is the **`Connector` Protocol**. Telegram is the one
active connector today; everything downstream of a connector (normalize → context → extract → review)
is source-agnostic.

### The contract

`worker/src/aiwip_worker/connectors/base.py`:

```python
@runtime_checkable
class Connector(Protocol):
    def fetch_messages(
        self, chat_external_id: int, after_message_id: int | None = None, limit: int = 200
    ) -> list[FetchedMessage]:
        """Return messages with id > after_message_id, ascending, capped at `limit`."""
        ...
```

A connector is any object with that one method. It returns `FetchedMessage` dataclasses — the normalized
shape the sync engine consumes:

```python
@dataclass
class FetchedMessage:
    external_message_id: int
    sender_external_id: int | None
    sender_username: str | None
    sender_display_name: str | None
    text: str | None
    sent_at: dt.datetime
    raw: dict = field(default_factory=dict)
    message_type: str = "text"        # text | voice | image | document | mixed
    attachments: list = field(default_factory=list)  # list[FetchedAttachment]

@dataclass
class FetchedAttachment:
    attachment_type: str              # voice | image | document
    file_name: str | None = None
    mime_type: str | None = None
```

Incremental sync works by `after_message_id`: the engine persists the last external message id per chat
(`sync_states.last_external_message_id`) and passes it back on the next call, so each connector must
return messages **with id strictly greater than `after_message_id`, in ascending order**, capped at
`limit`. Attachments are recorded as **metadata only** — there is no download or media processing yet.

### A skeleton custom connector

```python
# worker/src/aiwip_worker/connectors/slack.py
from __future__ import annotations

import datetime as dt
from .base import FetchedAttachment, FetchedMessage


class SlackConnector:
    def __init__(self, token: str | None = None):
        self._token = token or settings.slack_token   # add to core config + .env
        if not self._token:
            raise RuntimeError("Slack credentials missing — set SLACK_TOKEN.")

    def fetch_messages(
        self, chat_external_id: int, after_message_id: int | None = None, limit: int = 200
    ) -> list[FetchedMessage]:
        # Call your source API for messages newer than after_message_id, ascending.
        out: list[FetchedMessage] = []
        for raw in self._client.history(chat_external_id, after=after_message_id, limit=limit):
            out.append(
                FetchedMessage(
                    external_message_id=int(raw["id"]),
                    sender_external_id=raw.get("user_id"),
                    sender_username=raw.get("user_name"),
                    sender_display_name=raw.get("display_name"),
                    text=raw.get("text") or None,
                    sent_at=raw["ts"],          # tz-aware datetime
                    raw=raw,
                    message_type="text",
                    attachments=[],             # or FetchedAttachment(...) metadata
                )
            )
        return out
```

Because `Connector` is `runtime_checkable`, `isinstance(SlackConnector(), Connector)` is `True` once the
method shape matches — no base class to inherit.

### Registering a new source

1. **Enable the `ConnectorType`.** It already exists as a reserved enum in
   `core/src/aiwip_core/models.py` — `telegram` (active) plus `slack`, `email`, `whatsapp`, `discord`
   (reserved/future). To activate one, treat it as a real source in the sync path (see below). Adding a
   brand-new type means a new enum member and a Postgres enum migration.
2. **Wire it into the consumer.** `worker/src/aiwip_worker/consumer.py` currently hard-codes Telegram:
   ```python
   def _build_connector() -> Connector:
       return TelegramConnector()
   ```
   Make this select by connector type (e.g. branch on the chat's `connector_type` or the job payload)
   and return your connector. `process_job`, `run_pipeline`, and `sync.run_sync` already take a
   `Connector`, so nothing else changes.
3. **Key chats by external id.** Chats are uniquely keyed by `(connector_type, external_chat_id)`
   (`uq_chats_connector_external`). `get_or_create_chat()` in the consumer currently creates Telegram
   chats; generalize it to set the right `connector_type` for your source, and use that source's native
   chat/channel id as `external_chat_id`. The per-chat `sync_states` row then tracks incremental
   progress independently per source.

Slack / Email / WhatsApp / Discord are **reserved enum values only** — they have no implementation; the
steps above are what it takes to make one real.

---

## 2. AI provider (OpenAI)

Extraction is the only AI call in the system, and it only ever produces **Candidates** — never
WorkItems.

### Configuration

| Var | Default | Notes |
|---|---|---|
| `OPENAI_API_KEY` | — | Required for extraction; absent → no candidates. |
| `OPENAI_MODEL` | `gpt-4o-mini` | Any OpenAI model that supports Structured Outputs. |

### How it works

- **Structured Outputs.** The call uses a strict JSON schema (`JSON_SCHEMA` in
  `worker/src/aiwip_worker/llm/prompts.py`), so the model returns validated JSON: a list of
  `candidates` plus a `context_summary` / `context_confidence`. Output is re-validated against
  `llm/schema.py` (`LLMOutput`); invalid output is logged and skipped, never crashing the pipeline.
- **Prompt versioning.** `PROMPT_VERSION` (currently **`v2`**, recall-tuned) is stored on every
  `ai_runs` row and every `candidate`, so quality changes are attributable. **Bump it on any prompt
  change** — it is the single most important eval lever. v2 captures `task` / `request` / `reminder` /
  `idea` / `knowledge` and deliberately ignores chatter, reactions, jokes, emoji-only, and gibberish.
- **Confidence bands** (per-item, applied in `extract.py`):
  | item confidence | result |
  |---|---|
  | `≥ 0.90` | candidate created with status `new` |
  | `0.60 – 0.90` | candidate created with status `needs_review` |
  | `< 0.60` | skipped (too weak) |
  If no assignee resolves, a `new` candidate is downgraded to `needs_review` and `assignee` is added to
  `missing_fields`.
- **Observability.** Every call is logged to the `ai_runs` table: model, prompt version, input hash
  (`D23` idempotency), token counts, cost, status, and the full input/output payloads.

### Swapping or tuning

- **Tune recall/precision:** edit the system prompt in `prompts.py` and **bump `PROMPT_VERSION`**. Use
  `scripts/extract_dryrun.py` (see [`RUNNING.md`](RUNNING.md#seeding-demo-data--dry-running-extraction))
  to preview results against real messages without writing to the DB.
- **Change model:** set `OPENAI_MODEL`.
- **Swap provider:** replace `worker/src/aiwip_worker/llm/client.py` (`OpenAIClient`) with a client that
  exposes the same `extract(system, user, json_schema) -> result` interface returning `model`, `output`,
  `tokens_input`, `tokens_output`, `cost`, `status`, `error`. `extract_candidates()` accepts an injected
  `client=`, so the rest of the pipeline is provider-agnostic.

---

## 3. The REST API (integration surface for external systems)

The API is a standard JSON REST surface and is the supported way for external systems to read and act on
aiwip data. Base URL `http://localhost:8000` (or via the web proxy at `/api/*`).

### Auth flow

1. `POST /api/auth/login` with `{"email","password"}`. On success the response sets an **httpOnly
   cookie `aiwip_session`** (bcrypt-checked credentials → an opaque Redis-backed session token,
   7-day TTL).
2. Send that cookie on every subsequent request.
3. `POST /api/auth/logout` destroys the session; `GET /api/auth/me` returns the current user.

There is no API-key/bearer scheme — integrations authenticate as a user via the session cookie. Use a
dedicated admin (or assignee) user for machine clients and keep its credentials in a secret store.

**Roles:** **admin** = everything. **assignee** = may only *view and transition their own* work items
(scoped via the `assignees.user_id` link); all admin-only endpoints return `403` for them.

### Endpoint reference

| Group | Method & path | Purpose | Role |
|---|---|---|---|
| **Auth** | `POST /api/auth/login` | Log in; sets `aiwip_session` cookie | any |
| | `POST /api/auth/logout` | Destroy the session | any (authenticated) |
| | `GET /api/auth/me` | Current user | any (authenticated) |
| **Users** | `GET /api/users` | List users | admin |
| | `POST /api/users` | Create a user (admin or assignee role) | admin |
| **Sync** | `POST /api/sync/run` | Enqueue a sync (body `{chat_id?}`; defaults to `TELEGRAM_CHAT_ID`) → `202` | admin |
| | `GET /api/sync/status` | Queue length, latest run, per-chat sync state | admin |
| | `GET /api/sync/history` | Recent `sync_runs` (read/saved counts, status, errors) | admin |
| **Candidates** | `GET /api/candidates` | List candidates (filter `?status=`) | admin |
| | `GET /api/candidates/{id}` | Candidate detail + assignees + source messages | admin |
| | `PATCH /api/candidates/{id}` | Edit fields (title/summary/type/priority/due_date) | admin |
| | `POST /api/candidates/{id}/approve` | Promote to a WorkItem → `201` | admin |
| | `POST /api/candidates/{id}/reject` | Reject (kept in history) | admin |
| **Work items / board** | `GET /api/work-items` | List work items (filter `?status=`) | admin / assignee (scoped) |
| | `GET /api/work-items/board` | Kanban — items grouped by the 9 statuses | admin / assignee (scoped) |
| | `GET /api/work-items/{id}` | Work item detail + assignees + labels | admin / assignee (scoped) |
| | `POST /api/work-items/{id}/status` | Change status (audited) | admin / assignee (own) |
| | `POST /api/work-items/{id}/labels` | Attach a label → `201` | admin |
| **Assignees** | `GET /api/assignees` | List (filter `?active=`) | admin |
| | `POST /api/assignees` | Create an assignee | admin |
| | `PATCH /api/assignees/{id}` | Update an assignee | admin |
| **Labels** | `GET /api/labels` | List labels | admin |
| | `POST /api/labels` | Create a label | admin |
| **Audit** | `GET /api/audit` | Audit log (filters: `entity_type`, `action`, `actor_user_id`, `limit`) | admin |
| **Evaluation** | `POST /api/evaluation/cases` | Create an eval case (optionally seeded from a candidate) | admin |
| | `GET /api/evaluation/cases` | List eval cases | admin |
| | `GET /api/evaluation/reports` | Pass/fail/partial metrics, by prompt version | admin |

WorkItem statuses (board columns): `inbox`, `backlog`, `ready`, `in_progress`, `blocked`, `review`,
`done`, `cancelled`, `archived`.

### curl examples

```bash
# 1. Log in → store the session cookie in a jar
curl -s -c cookies.txt -X POST http://localhost:8000/api/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"you@example.com","password":"change-me"}'

# 2. List work items (send the cookie)
curl -s -b cookies.txt http://localhost:8000/api/work-items

# 3. Move a work item to "in_progress"
curl -s -b cookies.txt -X POST http://localhost:8000/api/work-items/42/status \
  -H 'content-type: application/json' \
  -d '{"status":"in_progress"}'
```

Through the web proxy the same calls work against `http://localhost:3000/api/...` with the browser's
cookie.

---

## 4. Data stores as integration points

If you prefer to read aiwip data directly (BI, exports, downstream sync), both stores are accessible.

### Postgres (system of record)

19 tables; the integration-relevant highlights:

- **`candidates`** — AI output awaiting review: type, title, summary, priority, due date, status, the
  five per-field confidence scores, `missing_fields`, `context_summary`, `model_name`,
  `prompt_version`. Linked to source messages via `candidate_messages` and to people via
  `candidate_assignees`.
- **`work_items`** — the approved, human-confirmed records. Each has `source_candidate_id` (1:1
  traceability back to the candidate), `status`, snapshotted `reasoning` / `confidence`, plus
  `work_item_assignees` and `work_item_labels`.
- **`assignees`** — the finite list the AI resolver matches against (display name, telegram username,
  aliases); optionally linked to a `users` row (`user_id`) for assignee-role login scoping.
- **`messages`** — ingested source messages (`external_message_id`, sender, text, normalized content,
  processing status). `sync_states` / `sync_runs` track ingestion progress and history.
- **`audit_logs`** — append-only trail of every review/sync/assignee action (actor, action, entity,
  before/after JSON).
- **`ai_runs`** — every model call (model, prompt version, tokens, cost, status, input/output payloads).

Connect with the same credentials as the app:
```
postgresql+psycopg://aiwip:aiwip@localhost:5432/aiwip
```
Prefer **read-only** access for external consumers, and treat `work_items` (not `candidates`) as the
source of confirmed work.

### Redis

Two roles:
- **Sessions** — `session:<token>` keys map a session token to a user id (7-day TTL). Created on login,
  referenced by the `aiwip_session` cookie. Treat as opaque; auth is owned by the API.
- **Job queue** — a single Redis list `aiwip:jobs` holds JSON sync jobs (`{type:"telegram.sync",
  chat_id, trigger, user_id, attempts}`). Producers `LPUSH`, the worker `BRPOP`s. You *can* enqueue a
  job by pushing to this list, but the supported trigger is `POST /api/sync/run`.

---

## 5. Outbound / notifications & downstream tools (future / extension)

> **Status: not yet implemented.** This section describes where outbound integrations would attach. The
> system today is inbound + review only; there is no push to external trackers or notifier.

Likely integrations and their natural hook points:

- **Push approved work items to a tracker (Jira / Linear / GitHub Issues, etc.).** The clean trigger is
  candidate **approval** — `approve_candidate` in `api/src/aiwip_api/routers/candidates.py`
  (and `core` `promotion.approve_candidate`), which is exactly where a WorkItem is created. Emitting a
  "work item created" event there (or in a worker job reacting to a new `work_items` row) would let a
  downstream connector create the external ticket and store the external id alongside the WorkItem.
- **Status mirroring.** `POST /api/work-items/{id}/status` is the single chokepoint for status changes
  (already audited as `work_item_status_changed`) — the place to mirror transitions out to a tracker, or
  to ingest status changes back in.
- **Notifications (Slack/email/Telegram reply).** A new outbound job type on the existing Redis queue
  (mirroring `telegram.sync`) keeps notifications off the request path; the worker already has a job
  loop to extend.
- **Reusing the connector layer for outbound.** The inbound `Connector` Protocol is read-only
  (`fetch_messages`). An outbound capability would be a **separate** interface (e.g. `post_message` /
  `create_ticket`), not an extension of `Connector`, so inbound and outbound stay decoupled.

Until built, the supported integration path for downstream systems is **polling the REST API**
(`GET /api/work-items`, `GET /api/work-items/board`, `GET /api/audit`) or **reading Postgres**
(`work_items` + `audit_logs`).
