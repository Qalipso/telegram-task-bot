# Database Design

> Document 4 of the **AI Work Intelligence Platform** documentation set.
> This is the canonical English version (`database-design.md`); a maintained Russian copy also exists.

## Core Tables

### `users`
Web-system users.

```text
id
email
display_name
role
created_at
updated_at
```

Roles:

```text
admin
assignee
```

### `chats`
Telegram chats or channels.

```text
id
connector_type
external_chat_id
title
is_active
created_at
updated_at
```

### `connector_accounts`
Connection settings.

```text
id
connector_type
name
status
credentials_ref
created_at
updated_at
```

MVP: `telegram`. Future: `slack`, `email`, `whatsapp`, `discord`.

### `messages`
Normalized messages.

```text
id
chat_id
external_message_id
sender_external_id
sender_username
sender_display_name
message_type
text_content
normalized_content
sent_at
synced_at
raw_payload
processing_status
created_at
```

`message_type`: `text | voice | image | document | mixed`

`processing_status`: `new | normalized | analyzed | failed | skipped`

Indexes: `chat_id`, `external_message_id`, `sent_at`, `processing_status`

Unique: `chat_id + external_message_id`

### `message_attachments`
Files, photos, voice messages, and documents.

```text
id
message_id
attachment_type
file_name
mime_type
storage_path
extracted_text
vision_summary
transcript
processing_status
created_at
```

`attachment_type`: `voice | image | document`

`processing_status`: `new | processing | processed | failed | skipped`

### `sync_states`
Current synchronization state for each chat.

```text
id
chat_id
last_synced_at
last_external_message_id
last_successful_sync_at
status
last_error
updated_at
```

### `sync_runs`
History of synchronization runs.

```text
id
trigger_type
status
started_at
finished_at
messages_read
messages_saved
messages_failed
candidates_created
error_message
created_by_user_id
```

`trigger_type`: `scheduled | manual | retry`

`status`: `running | success | partial_success | failed`

### `assignees`
Assignees.

```text
id
user_id
telegram_user_id
telegram_username
display_name
aliases
is_active
created_at
updated_at
```

Store `aliases` as a JSON array.

### `candidates`
AI candidates pending approval.

```text
id
candidate_type
title
summary
priority
due_date
status

task_confidence
context_confidence
assignee_confidence
priority_confidence
due_date_confidence

reasoning_summary
missing_fields
context_summary
model_name
prompt_version

created_at
updated_at
reviewed_at
reviewed_by_user_id
```

`missing_fields`: jsonb — list of fields the LLM could not resolve.

`context_summary`: text — snapshot of the analyzed context window.

`candidate_type`: `task | request | reminder | idea | knowledge | decision_future | risk_future`

`status`: `new | needs_review | edited | approved | rejected | duplicate | error`

`priority`: `critical | high | medium | low | null`

### `candidate_messages`
Link between a candidate and its source messages.

```text
id
candidate_id
message_id
role
created_at
```

`role`: `primary | context | supporting`

### `candidate_assignees`
Multiple assignees on a candidate.

```text
id
candidate_id
assignee_id
confidence
is_primary
created_at
```

### `candidate_labels`
Labels (tags) attached to a candidate.

```text
id
candidate_id
label_id
created_at
```

### `work_items`
Confirmed work items.

```text
id
source_candidate_id
type
title
summary
priority
due_date
status
reasoning
confidence
created_at
updated_at
created_by_user_id
```

`type`: `task | request | reminder | idea | knowledge`

`status`: `inbox | backlog | ready | in_progress | blocked | review | done | cancelled | archived`

`reasoning`: text — snapshot from the candidate at approval.

`confidence`: real — snapshot from the candidate at approval.

Tags are attached via `work_item_labels`.

### `work_item_assignees`

```text
id
work_item_id
assignee_id
created_at
```

### `labels`
Master tag vocabulary referenced by the label join tables.

```text
id
name
color
created_at
```

`color`: nullable.

### `work_item_labels`
Labels (tags) attached to a work item.

```text
id
work_item_id
label_id
created_at
```

### `ai_runs`
All AI runs.

```text
id
run_type
model_provider
model_name
prompt_version
input_hash
input_payload
output_payload
tokens_input
tokens_output
cost
status
error_message
created_at
```

`run_type`: `classification | extraction | due_date_resolution | vision_analysis | document_analysis | evaluation`

### `evaluation_cases`
Golden dataset / AI Eval.

```text
id
source_message_ids
input_payload
expected_output
actual_output
result
score
comments
model_name
prompt_version
created_at
updated_at
```

`result`: `pass | fail | partial | pending`

### `audit_logs`

```text
id
actor_user_id
action
entity_type
entity_id
before_value
after_value
created_at
```

Actions:

```text
sync_started
sync_finished
candidate_created
candidate_edited
candidate_approved
candidate_rejected
work_item_status_changed
assignee_created
assignee_updated
```

## Important Constraints

- A single `chat_id + external_message_id` pair cannot repeat.
- One candidate can be linked to multiple messages.
- One candidate can have multiple assignees.
- One approved candidate creates one work_item.
- On approval, candidate_assignees are copied to work_item_assignees (carry is_primary).
- All AI runs must be persisted to `ai_runs`.
