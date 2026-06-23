# Domain Model

> Документ 2 из набора документации **AI Work Intelligence Platform**.
> Каноничная версия — английская (`domain-model.md`); это поддерживаемая русская копия.

## Core Principle

Система работает вокруг универсальной сущности **WorkItem**.

Все найденные объекты проходят путь:

```text
Source Content
→ Candidate
→ Review
→ Work Item
```

## Entities

### Connector

Источник данных.

Типы:

- Telegram
- Future: Slack, Email, WhatsApp, Discord

### Message

Нормализованное сообщение. Может быть получено из:

- Text
- Voice Transcript
- Image OCR
- Document Extraction

Каждое сообщение принадлежит одному Connector и одному Chat.

### Chat

Источник сообщений. Содержит множество сообщений.

### Context Window

Логическая группа сообщений, используемая для анализа. Формируется из последних сообщений и
связанных обсуждений. **Не является отдельной сущностью** для пользователя.

### Candidate

Результат AI-анализа.

Типы:

- Task
- Request
- Reminder
- Idea
- Knowledge
- Future: Decision, Risk

Статусы:

- New
- Needs Review
- Edited
- Approved
- Rejected
- Duplicate
- Error

Где: Needs Review = низкая уверенность / требует проверки человеком; Duplicate = совпал с существующим объектом; Error = анализ завершился ошибкой.

### WorkItem

Основная рабочая сущность системы.

Поля:

- Title
- Summary
- Type
- Priority
- Tags
- Assignees
- Due Date
- Status
- Reasoning
- Confidence
- Source Messages
- Created At
- Updated At

### User

Пользователь системы.

Роли:

- Admin
- Assignee

### Assignee

Исполнитель. Связан с Telegram ID. Содержит aliases для сопоставления.

### SyncRun

История синхронизаций. Хранит:

- Start
- Finish
- Status
- Messages Processed
- Candidates Found
- Errors

### EvaluationCase

Запись для AI Evaluation. Содержит:

- Input
- Expected Result
- Actual Result
- Pass/Fail
- Comments
- Version
- Model
- Prompt

### Audit Log

Журнал действий. Фиксирует:

- Approval
- Rejection
- Status Change
- Manual Edit
- Sync Operations
