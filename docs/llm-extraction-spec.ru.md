# LLM Extraction Specification

> Документ 5 из набора документации **AI Work Intelligence Platform**.
> Каноничная версия — английская (`llm-extraction-spec.md`); это поддерживаемая русская копия.

## Purpose

LLM pipeline должен анализировать сохранённые сообщения и создавать структурированные Work Item
Candidates. Система **не создаёт финальные Work Items автоматически** — все найденные элементы
проходят human approval.

## Input

LLM получает Context Window из БД. Context Window включает:

- новые сообщения
- предыдущие сообщения, если они относятся к той же теме
- reply chain
- quoted messages
- metadata об авторах
- текущую дату и время в UTC
- список доступных assignees
- список aliases

## Output

LLM должен возвращать структурированный JSON.

Корневой объект:

```json
{
  "candidates": [],
  "context_summary": "",
  "context_confidence": 0
}
```

### Candidate Schema

```json
{
  "type": "task",
  "title": "",
  "summary": "",
  "priority": "medium",
  "due_date": null,
  "assignees": [],
  "source_message_ids": [],
  "supporting_message_ids": [],
  "reasoning_summary": "",
  "missing_fields": [],
  "confidence": {
    "item": 0,
    "context": 0,
    "assignee": 0,
    "priority": 0,
    "due_date": 0
  }
}
```

### Candidate Types

```text
task
request
reminder
idea
knowledge
```

Future placeholders: `decision`, `risk`.

### Priority Values

```text
critical
high
medium
low
null
```

Rules:

- Если приоритет явно указан — использовать указанный.
- Если приоритет не указан — модель может определить сама.
- Если информации недостаточно — вернуть null.
- Critical использовать только при явной срочности, блокере, риске срыва или бизнес-критичном
  действии.

### Assignee Rules

- Исполнители выбираются только из конечного списка assignees.
- Можно выбрать несколько исполнителей.
- Если исполнитель не определён — candidate помечается как requiring review.
- Если несколько возможных исполнителей — вернуть варианты с confidence.
- Не создавать нового исполнителя автоматически.
- Автор сообщения может быть исполнителем только если контекст явно указывает на это.

### Due Date Rules

- Использовать текущую дату и время в UTC.
- Относительные даты переводить в календарную дату.
- Неоднозначные даты возвращать с низким confidence.
- Если срок не определён — `due_date = null`.
- Если `due_date = null`, candidate всё равно создаётся.

### Context Rules

- Анализировать не одно сообщение, а окно сообщений.
- Использовать последние 20 сообщений из БД.
- Если тема продолжается, учитывать предшествующий контекст.
- Если началась новая тема, не смешивать её с предыдущей.
- Для task recognition важнее точность, чем полнота.
- Ложные задачи хуже, чем пропущенные слабые сигналы.

### Confidence Rules

```text
item_confidence > 0.90 = strong candidate
0.70–0.90 = candidate requires review
< 0.70 = usually skip or mark low confidence
```

Target metrics:

```text
Task Recognition > 90%
Context Understanding > 80%
```

### Missing Fields

Possible values: `assignee`, `priority`, `due_date`, `context`, `source`.

Если отсутствует обязательное поле, UI должен подсвечивать candidate.

## AI Run Logging

Для каждого запуска сохранять:

```text
model_provider
model_name
prompt_version
input_payload
output_payload
tokens_input
tokens_output
cost
status
error_message
```

## Error Handling

Если LLM вернул невалидный JSON:

- сохранить AI run как failed
- не ломать весь sync
- пометить batch как `partial_success`
- дать возможность retry

Если confidence низкий:

- не создавать WorkItem
- создать Candidate только если есть полезная информация
- пометить `needs_review`

## Human Feedback Loop

После review сохранять:

```text
approved
rejected
edited_then_approved
```

Эти данные используются для Evaluation Dataset.
