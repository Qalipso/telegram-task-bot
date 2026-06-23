# Technical Architecture Overview

> Документ 3 из набора документации **AI Work Intelligence Platform**.
> Каноничная версия — английская (`architecture.md`); это поддерживаемая русская копия.

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

Отвечает за получение данных.

Интерфейс `Connector`:

- `fetchMessages()`
- `fetchMedia()`
- `fetchMetadata()`

MVP: `TelegramConnector`.

## Sync Layer

Запускается по расписанию и вручную. Отвечает за:

- получение новых сообщений
- сохранение состояния синхронизации
- защиту от повторного чтения

## Content Normalization Layer

Преобразует различные типы данных в единый формат:

- Text → Text
- Voice → Transcript
- Image → OCR + Vision Description
- PDF → Extracted Text
- DOCX → Extracted Text
- XLSX → Extracted Text
- PPTX → Extracted Text

Результат: **Normalized Content**.

> **Голос не транскрибируется автоматически.** Маппинг `Voice → Transcript` применяется только после
> ручного запуска транскрипции админом (`voice.transcribe_manual`) — см. `system-spec.md` §9.

## Context Builder

Формирует окно анализа. Правила:

- Использовать сохранённые сообщения из БД.
- Использовать последние сообщения в контексте.
- Если обнаружено продолжение обсуждения — расширять контекст назад.
- Если обнаружена новая тема — начинать новый контекст.

## AI Analysis Pipeline

Этапы:

1. Classification
2. Entity Extraction
3. Assignee Resolution
4. Priority Resolution
5. Due Date Resolution
6. Confidence Scoring
7. Candidate Generation

## Review Layer

Все кандидаты требуют подтверждения. Возможные действия: **Approve / Reject / Edit**. После
подтверждения создаётся WorkItem.

## Work Management Layer

Kanban Board. Статусы:

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

Каждый Candidate может участвовать в датасете. Сохраняются:

- Prompt
- Model
- Response
- Cost
- Tokens
- Expected Result
- Actual Result
- Evaluation Result

## Audit Layer

Логирует: Sync Events, Approvals, Rejections, Status Changes, Manual Updates, User Actions.

## Deployment

- Frontend: Next.js
- Backend: FastAPI
- Database: PostgreSQL
- Queue: Redis
- Workers: Python
- Containerization: Docker

---

## Основные flow'ы

> Перенесено из прежней дизайн-спеки; приведено к новой модели (Candidate → WorkItem).

### Flow 1 — Автоматическая синхронизация
```text
Scheduler ставит sync-job (trigger=scheduled)
  → Worker читает sync_state.last_external_message_id для чата
  → Telegram Connector берёт сообщения с id > last_external_message_id (батчами)
  → новые сообщения сохраняются в messages (идемпотентно по chat_id+external_message_id)
  → Content Normalization приводит сообщения к normalized_content
  → Context Builder формирует окна анализа
  → AI Analysis Pipeline создаёт Candidates
  → обновляется sync_state; финализируется sync_run
```

### Flow 2 — Ручная синхронизация
```text
Пользователь жмёт Sync Now → backend ставит sync-job (trigger=manual)
  → UI опрашивает статус → worker выполняет чтение/анализ
  → после завершения обновляется dashboard
```

### Flow 3 — Разбор кандидатов
```text
Admin открывает Candidates → видит найденные элементы
  → редактирует поля при необходимости → approve / reject
  → approved-candidate становится WorkItem (status=inbox)
```

### Flow 4 — Управление исполнителями
```text
Admin открывает Assignees → добавляет/редактирует человека
  → указывает Telegram ID, username, aliases → отключает при необходимости
  → resolver использует активный список при следующем анализе
```

---

## Нефункциональные требования

> Перенесено из прежней дизайн-спеки.

**Надёжность:** sync не должен ломать всю систему; ошибки логируются и видны; частичный sync виден
(`partial_success`); повторный запуск не создаёт дубликаты.

**Безопасность:** доступ к UI только для авторизованных пользователей (email + пароль + сессия);
Telegram session / API-ключи и LLM API-ключ хранятся в env / secret store (`credentials_ref`),
никогда в коде; raw-сообщения не отдаются наружу без авторизации.

**Производительность:** sync обрабатывает сообщения батчами; LLM-вызовы ограничены (Batches API,
prompt caching, гейт `processing_status`); повторный анализ уже обработанных сообщений не нужен.

**Аудит:** хранить историю sync (`sync_runs`); источник каждого элемента (`candidate_messages`);
изменения через `audit_logs` (before/after).

---

## Раскладка репозитория (предлагаемая)

> Перенесено из прежней дизайн-спеки.

```text
telegram-task-bot/
├── docs/                  ← набор документации (этот файл и др., EN + RU)
├── docker-compose.yml
├── .env.example           ← документирует нужные секреты (без реальных значений)
├── worker/   (Python)     ← Telethon connector, sync worker, normalization, context builder,
│   ├── src/                  AI pipeline, resolver'ы, LLM-клиент, SQLAlchemy-модели
│   └── tests/
├── api/      (FastAPI)    ← REST endpoints, общие модели с worker
│   ├── src/
│   └── tests/
└── web/      (Next.js)    ← UI: dashboard, candidates, kanban, assignees, sync history
    └── ...
```
