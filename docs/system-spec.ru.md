# AI Work Intelligence Platform — Финальная системная спецификация

- **Версия:** 1.0
- **Статус:** Approved for MVP Development (утверждено к разработке MVP)
- **Роль:** Авторитетная спецификация верхнего уровня. Остальные документы в `docs/` (Product Brief,
  Domain Model, Architecture, Database Design, LLM Extraction Spec, Evaluation Plan, Test Plan,
  Decisions) — детальные сопроводительные документы и должны быть согласованы с этим.
- **Язык:** каноничен английский (`system-spec.md`); это поддерживаемая русская копия
  (`system-spec.ru.md`).

## 1. Product Overview

AI Work Intelligence Platform — внутренняя система управления работой, которая автоматически
анализирует переписку в Telegram, выявляет actionable рабочие элементы и превращает их в
структурированные workflow-объекты через процесс человеческого подтверждения.

Платформа выступает интеллектуальным слоем между коммуникацией команды и исполнением задач.

Главный принцип:

```text
Telegram Discussions
→ Context Understanding
→ AI Candidate Generation
→ Human Review
→ Work Item Creation
→ Kanban Workflow
```

Система ставит **precision выше recall**. Ложные срабатывания считаются вреднее, чем пропущенные
рабочие элементы с низкой уверенностью.

## 2. Product Goals

### Primary Goals
- Предотвращать потерю задач, скрытых в переписке
- Снижать ручное извлечение работы из Telegram
- Сохранять контекст обсуждений
- Создавать структурированный workflow из неструктурированной коммуникации
- Строить переиспользуемый датасет для AI-оценки и непрерывного улучшения

### Success Metrics
- Task Recognition Accuracy: `> 90%`
- Context Understanding Accuracy: `> 80%`
- Все рабочие элементы прослеживаются назад к исходным обсуждениям.

## 3. Scope

### MVP Scope
- **Communication Source:** Telegram
- **Work Item Types:** Task, Request, Reminder, Idea, Knowledge
- **Workflow:** обязательное человеческое подтверждение каждого AI-кандидата.
- **Board:** встроенная Kanban-доска.
- **AI:** OpenAI models.
- **Roles:** Admin, Assignee
- **Evaluation:** встроенный evaluation-датасет и основа для regression-тестирования.

### Future Scope
- Slack Connector
- Email Connector
- WhatsApp Connector
- Discord Connector
- Decision Detection
- Risk Detection
- Calendar Awareness
- Working Day Awareness
- Knowledge Graph
- Notifications
- Multi-Tenant Support

## 4. User Roles

### Admin
Permissions:
- Run sync
- Manage chats
- Manage assignees
- Review candidates
- Approve candidates
- Reject candidates
- Edit candidates
- Manage board
- Access evaluation
- Access audit logs

### Assignee
Permissions:
- View assigned work items
- Update work item status
- View board

## 5. Core Concepts

- **Message** — сырая единица коммуникации из Telegram. Источник: Text, Image, Voice, Document.
- **Candidate** — AI-предложение. Ещё не подтверждено. Требует человеческого ревью.
- **Work Item** — подтверждённый объект, используемый командой.
- **Context Window** — набор связанных сообщений, используемых для AI-рассуждения.
- **Assignee** — пользователь, который может владеть рабочими элементами.

## 6. Work Item Model

Work Item содержит:

```text
Title
Summary
Type
Priority
Tags
Assignees
Due Date
Status
Confidence
Reasoning
Source Messages
Created At
Updated At
```

### Types
```text
task
request
reminder
idea
knowledge
```
Future: `decision`, `risk`.

### Priority Levels
```text
critical
high
medium
low
null
```

### Statuses
```text
inbox
backlog
ready
in_progress
blocked
review
done
cancelled
archived
```

## 7. Communication Layer

Все источники коммуникации реализуют общий интерфейс коннектора.

- MVP: `TelegramConnector`
- Future: `SlackConnector`, `EmailConnector`, `WhatsAppConnector`, `DiscordConnector`

Обязанности коннектора:
- Fetch messages
- Fetch media
- Normalize sender information
- Normalize metadata

## 8. Telegram Integration

- **Technology:** Telethon
- **Reason:** доступ к истории Telegram и продвинутые возможности синхронизации.

### Sync Modes
- **Scheduled** — каждые 6 часов.
- **Manual** — синхронизация по инициативе админа.

## 9. Message Processing

### Supported Inputs
- **Text** — обрабатывается автоматически.
- **Image** — обрабатывается через OCR и vision-анализ.
- **Document** — поддерживаются: `pdf`, `docx`, `xlsx`, `pptx`. Текст извлекается автоматически.
- **Voice** — **не обрабатывается автоматически.** Админ может вручную запустить транскрипцию.

## 10. Content Normalization

Все входы превращаются в **Normalized Content**:

```text
Text   → normalized text
Image  → OCR text + vision summary
PDF    → extracted text
Voice  → transcript
```

AI pipeline потребляет только normalized content.

## 11. Context Builder

- **Context Source:** сообщения, сохранённые в БД.
- **Base Window:** 20 сообщений.

### Included Context
- Related messages
- Reply chains
- Quoted messages
- Sender metadata
- UTC timestamp
- Assignee list

### Topic Continuation Logic
- Если обсуждение продолжается: расширять контекст.
- Если обнаружена новая тема: начинать новый контекст.

## 12. AI Pipeline

### Pipeline Steps
1. Context Classification
2. Work Item Detection
3. Type Classification
4. Summary Generation
5. Assignee Resolution
6. Priority Resolution
7. Due Date Resolution
8. Confidence Scoring
9. Candidate Creation

### Assignee Resolution
- Только существующие assignees
- Несколько assignees допустимо
- Неизвестные assignees не создаются автоматически
- Неоднозначные назначения требуют ревью

### Due Date Resolution
- Timezone = UTC
- Относительные даты переводятся в календарные
- Неоднозначные даты помечаются низким confidence
- Отсутствующий срок допустим

## 13. Candidate Review System

Каждый AI-результат создаёт **Candidate**, а не **Work Item**.

### Candidate Statuses
```text
new
needs_review
edited
approved
rejected
duplicate
error
```

### Review Actions
```text
approve
reject
edit
```

- **Approval Flow:** Candidate → Approved → Work Item
- **Rejection Flow:** Candidate → Rejected. Отклонённые кандидаты остаются в истории.

## 14. Kanban Board

Статусы:
```text
Inbox
Backlog
Ready
In Progress
Blocked
Review
Done
Cancelled
Archived
```

- MVP: свободные переходы статусов.
- Future: контролируемые workflow-правила.

## 15. Tags System

MVP включает теги. Примеры:
```text
frontend
backend
design
research
bug
customer
urgent
release
```

Теги можно прикреплять к: Candidates, Work Items.

Используются для: фильтрации, поиска, отчётности.

## 16. Evaluation System

**Назначение:** измерять качество AI.

### Metrics
- Task Recognition Accuracy
- Context Understanding Accuracy
- Assignee Accuracy
- Priority Accuracy
- Due Date Accuracy
- False Positive Rate
- False Negative Rate

### Dataset Sources
- Approved candidates
- Edited candidates
- Rejected candidates
- Manual cases

### Evaluation Case
Содержит:
```text
Input
Expected Output
Actual Output
Result
Model
Prompt Version
```

### Reports
Показывают: Pass Rate, Fail Rate, Partial Rate, Accuracy per field, Cost, Tokens, Model comparison.

## 17. AI Observability

Каждый AI-вызов должен сохранять:
```text
Provider
Model
Prompt Version
Input
Output
Tokens Input
Tokens Output
Cost
Status
Error
```

Используется для: отладки, оценки, анализа стоимости, regression-тестирования.

## 18. Audit System

Все критичные действия логируются. Примеры:
```text
Sync Started
Sync Finished
Candidate Created
Candidate Approved
Candidate Rejected
Candidate Edited
Work Item Updated
Assignee Created
Assignee Updated
```

## 19. Database Overview

Основные сущности:
```text
users
assignees
chats
messages
message_attachments
sync_states
sync_runs
candidates
candidate_messages
candidate_assignees
candidate_labels
work_items
work_item_assignees
work_item_labels
ai_runs
evaluation_cases
audit_logs
```

## 20. API Overview

### Sync
```http
POST /api/sync/run
GET  /api/sync/status
GET  /api/sync/history
```

### Candidates
```http
GET   /api/candidates
GET   /api/candidates/:id
PATCH /api/candidates/:id
POST  /api/candidates/:id/approve
POST  /api/candidates/:id/reject
```

### Work Items
```http
GET   /api/work-items
PATCH /api/work-items/:id
POST  /api/work-items/:id/status
```

### Assignees
```http
GET   /api/assignees
POST  /api/assignees
PATCH /api/assignees/:id
```

### Evaluation
```http
GET  /api/evaluation/reports
POST /api/evaluation/run
```

## 21. Queue Architecture

Jobs:
```text
telegram.sync
message.normalize
attachment.extract_text
attachment.vision_analyze
voice.transcribe_manual
context.build
ai.extract_candidates
candidate.create
evaluation.run
```

Retry Policy:
```text
3 retries
exponential backoff
dead-letter support
```

## 22. Security

- **Authentication:** Email + Password
- **Authorization:** Admin, Assignee
- Секреты хранятся вне исходного кода.

Required secrets:
```text
Telegram Credentials
OpenAI API Key
Database URL
```

## 23. Deployment

Архитектура:
```text
Frontend (Next.js)
Backend (FastAPI)
Worker (Python)
PostgreSQL
Redis
```

- **Deployment Method:** Docker Compose
- MVP использует локальное файловое хранилище. Интеграция с S3 не требуется.

## 24. Non-Functional Requirements

### Reliability
- Нет дубликатов сообщений
- Безопасные retry
- Поддержка частичных сбоев

### Performance
- Обрабатывать 500 сообщений/день
- Batch-обработка
- Async-задачи

### Maintainability
- Абстракция коннекторов
- Версионирование промптов
- Auditability

### Observability
- Sync logs
- AI logs
- Evaluation reports

## 25. MVP Definition of Done

Система считается MVP-завершённой, когда:
- Telegram sync работает
- Сообщения сохраняются
- Context Builder работает
- AI генерирует кандидатов
- Human review работает
- Work Items создаются
- Kanban board работает
- Assignees работают
- Tags работают
- Audit logs работают
- AI runs логируются
- Evaluation dataset существует
- Docker-деплой работает

Итоговый workflow:
```text
Telegram
→ Sync
→ Context Builder
→ OpenAI Analysis
→ Candidate Review
→ Work Item
→ Kanban Board
→ Evaluation
```
