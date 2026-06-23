# Evaluation Plan

> Document 6 of the **AI Work Intelligence Platform** documentation set.
> This is the canonical English version (`evaluation-plan.md`); a maintained Russian copy exists (`evaluation-plan.ru.md`).

## Purpose

The Evaluation Plan exists to measure the quality of AI recognition of work items from
Telegram conversations. The goal of the system is not simply to find more items, but to find them accurately, with the
correct context, assignees, priority, and due dates.

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

The following are evaluated:

- Work Item detection
- type correctness
- title quality
- summary quality
- assignees correctness
- priority correctness
- due_date correctness
- context completeness
- absence of false tasks

## Dataset Structure

Each evaluation case must contain:

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

- **Clear Task** — a direct assignment with an assignee and a due date.
- **Multi-Message Task** — a task that forms across several messages.
- **Request** — a request that may become a work item.
- **Reminder** — a reminder or follow-up.
- **Idea** — an idea that needs to be saved.
- **Knowledge** — useful information for the future.
- **No Task** — ordinary conversation that should not create a candidate.
- **Ambiguous Assignee** — there are several possible assignees.
- **Ambiguous Due Date** — the due date is stated implicitly.
- **Media-Based Item** — a work item extracted from a document, image, or voice message.

## Scoring

- **Pass** — the AI correctly found the item and the primary fields.
- **Partial** — the AI found the item but got one or more secondary fields wrong.
- **Fail** — the AI did not find the item or created a false item.

### Field-Level Scoring

Each field is scored separately:

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

Every user action is used as feedback:

- **Approved** — the model correctly found the candidate.
- **Edited then Approved** — the model found the candidate but got the details wrong.
- **Rejected** — the model created a false candidate.

This data feeds into the Evaluation Dataset.

## Regression Testing

After every change (prompt, model, context builder, assignee resolver, due date resolver),
the evaluation dataset must be re-run.

## Minimum Dataset Size

- MVP: `50 cases`
- Stable version: `200+ cases`
- Production confidence: `500+ cases`

## Evaluation Reports

Each report must show:

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

MVP AI quality is considered acceptable if:

- Task Recognition Accuracy >= 90%
- Context Understanding Accuracy >= 80%
- False Positive Rate is acceptable for manual review
- All errors can be reviewed and used to improve the dataset
