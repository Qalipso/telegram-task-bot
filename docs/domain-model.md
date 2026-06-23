# Domain Model

> Document 2 of the **AI Work Intelligence Platform** documentation set.
> This is the canonical English version (`domain-model.md`); the Russian copy (`domain-model.ru.md`) is maintained alongside it.

## Core Principle

The system is built around the universal **WorkItem** entity.

Every object that is discovered follows this path:

```text
Source Content
→ Candidate
→ Review
→ Work Item
```

## Entities

### Connector

A data source.

Types:

- Telegram
- Future: Slack, Email, WhatsApp, Discord

### Message

A normalized message. It can be derived from:

- Text
- Voice Transcript
- Image OCR
- Document Extraction

Each message belongs to exactly one Connector and one Chat.

### Chat

A source of messages. It contains many messages.

### Context Window

A logical group of messages used for analysis. It is built from the most recent messages and
related discussions. It is **not a separate entity** from the user's point of view.

### Candidate

The result of AI analysis.

Types:

- Task
- Request
- Reminder
- Idea
- Knowledge
- Future: Decision, Risk

Statuses:

- New
- Needs Review
- Edited
- Approved
- Rejected
- Duplicate
- Error

Where: Needs Review = low confidence / requires human review; Duplicate = matched an existing item; Error = analysis failed.

### WorkItem

The system's primary working entity.

Fields:

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

A user of the system.

Roles:

- Admin
- Assignee

### Assignee

An executor. Linked to a Telegram ID. Holds aliases for matching.

### SyncRun

The synchronization history. It stores:

- Start
- Finish
- Status
- Messages Processed
- Candidates Found
- Errors

### EvaluationCase

A record for AI Evaluation. It contains:

- Input
- Expected Result
- Actual Result
- Pass/Fail
- Comments
- Version
- Model
- Prompt

### Audit Log

An action log. It records:

- Approval
- Rejection
- Status Change
- Manual Edit
- Sync Operations
