# Database Design

> Документ 4 из набора документации **AI Work Intelligence Platform**.
> Каноничная версия — английская (`database-design.md`); это поддерживаемая русская копия.

## Core Tables

### `users`
Пользователи web-системы.

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
Telegram-чаты или каналы.

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
Настройки подключений.

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
Нормализованные сообщения.

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
Файлы, фото, голосовые и документы.

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
Текущее состояние синхронизации по каждому чату.

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
История запусков синхронизации.

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
Исполнители.

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

`aliases` хранить как JSON array.

### `candidates`
AI-кандидаты перед approval.

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

`missing_fields`: jsonb — список полей, которые LLM не смогла определить.

`context_summary`: text — снимок проанализированного окна контекста.

`candidate_type`: `task | request | reminder | idea | knowledge | decision_future | risk_future`

`status`: `new | needs_review | edited | approved | rejected | duplicate | error`

`priority`: `critical | high | medium | low | null`

### `candidate_messages`
Связь кандидата с исходными сообщениями.

```text
id
candidate_id
message_id
role
created_at
```

`role`: `primary | context | supporting`

### `candidate_assignees`
Несколько исполнителей на кандидате.

```text
id
candidate_id
assignee_id
confidence
is_primary
created_at
```

### `candidate_labels`
Метки (теги), привязанные к кандидату.

```text
id
candidate_id
label_id
created_at
```

### `work_items`
Подтверждённые рабочие элементы.

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

`reasoning`: text — снимок из кандидата на момент approval.

`confidence`: real — снимок из кандидата на момент approval.

Теги привязываются через `work_item_labels`.

### `work_item_assignees`

```text
id
work_item_id
assignee_id
created_at
```

### `labels`
Мастер-словарь тегов, на который ссылаются label-таблицы связей.

```text
id
name
color
created_at
```

`color`: nullable.

### `work_item_labels`
Метки (теги), привязанные к рабочему элементу.

```text
id
work_item_id
label_id
created_at
```

### `ai_runs`
Все AI-запуски.

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

- Один `chat_id + external_message_id` не может повторяться.
- Один candidate может быть связан с несколькими messages.
- Один candidate может иметь несколько assignees.
- Один approved candidate создаёт один work_item.
- On approval, candidate_assignees are copied to work_item_assignees (carry is_primary).
- Все AI-запуски должны сохраняться в `ai_runs`.
