# Evaluation Plan

> Документ 6 из набора документации **AI Work Intelligence Platform**.
> Каноничная версия — английская (`evaluation-plan.md`); это поддерживаемая русская копия.

## Purpose

Evaluation Plan нужен, чтобы измерять качество AI-распознавания рабочих элементов из
Telegram-переписки. Цель системы — не просто находить больше элементов, а находить их точно, с
правильным контекстом, исполнителями, приоритетом и сроками.

## Target Metrics

### Primary Metrics
- Task Recognition Accuracy > 90%
- Context Understanding Accuracy > 80%

### Secondary Metrics
- Assignee Accuracy
- Priority Accuracy
- Due Date Accuracy
- False Positive Rate
- False Negative Rate
- Review Correction Rate

## Evaluation Objects

Оцениваются:

- обнаружение Work Item
- правильность типа
- качество title
- качество summary
- правильность assignees
- правильность priority
- правильность due_date
- полнота контекста
- отсутствие ложных задач

## Dataset Structure

Каждый evaluation case должен содержать:

- input messages
- expected candidates
- expected type
- expected title
- expected summary
- expected assignees
- expected priority
- expected due date
- expected source messages
- expected context messages
- reviewer notes

## Evaluation Case Types

- **Clear Task** — прямое поручение с исполнителем и сроком.
- **Multi-Message Task** — задача формируется через несколько сообщений.
- **Request** — просьба, которая может стать рабочим элементом.
- **Reminder** — напоминание или follow-up.
- **Idea** — идея, которую нужно сохранить.
- **Knowledge** — полезная информация для будущего.
- **No Task** — обычная переписка, которая не должна создавать candidate.
- **Ambiguous Assignee** — есть несколько возможных исполнителей.
- **Ambiguous Due Date** — срок указан неявно.
- **Media-Based Item** — рабочий элемент извлечён из документа, картинки или голосового сообщения.

## Scoring

- **Pass** — AI корректно нашёл элемент и основные поля.
- **Partial** — AI нашёл элемент, но ошибся в одном или нескольких вторичных полях.
- **Fail** — AI не нашёл элемент или создал ложный элемент.

### Field-Level Scoring

Каждое поле оценивается отдельно:

```text
type
title
summary
assignees
priority
due_date
source_messages
context_messages
```

## Review Feedback Loop

Каждое действие пользователя используется как feedback:

- **Approved** — модель корректно нашла candidate.
- **Edited then Approved** — модель нашла candidate, но ошиблась в деталях.
- **Rejected** — модель создала ложный candidate.

Эти данные попадают в Evaluation Dataset.

## Regression Testing

После каждого изменения (prompt, модели, context builder, assignee resolver, due date resolver)
нужно прогонять evaluation dataset повторно.

## Minimum Dataset Size

- MVP: `50 cases`
- Стабильная версия: `200+ cases`
- Production confidence: `500+ cases`

## Evaluation Reports

Каждый отчёт должен показывать:

- model
- prompt version
- dataset version
- total cases
- pass rate
- partial rate
- fail rate
- field-level accuracy
- false positives
- false negatives
- cost
- tokens
- regression diff

## Success Criteria for MVP

MVP AI quality считается приемлемым, если:

- Task Recognition Accuracy >= 90%
- Context Understanding Accuracy >= 80%
- False Positive Rate приемлем для ручного review
- Все ошибки можно просмотреть и использовать для улучшения dataset
