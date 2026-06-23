# Product Brief

> Document 1 of the **AI Work Intelligence Platform** documentation set.
> This English version (`product-brief.md`) is the canonical version; the Russian copy is maintained alongside it.

## Product Name

AI Work Intelligence Platform

## Vision

Build an internal system that automatically turns work discussions into
structured work items without the need to manually transfer information out of Telegram.

The system should help the team capture tasks, requests, reminders, and ideas while preserving the context
of decision-making and reducing the chance of losing important agreements.

## Problem

The primary work communication happens in Telegram.

During discussions, the following regularly come up:

- tasks
- requests
- reminders
- ideas

These items get lost within the message stream and require manual transfer into a task management
system.

As a result:

- tasks are forgotten
- context is lost
- managers spend time manually sorting through the correspondence

## Target Users

**Admin** — manages the system, confirms detected items, manages assignees.

**Assignee** — receives work items and manages their statuses.

## Success Metrics

- Task Recognition Accuracy > 90%
- Context Understanding Accuracy > 80%
- Less manual sorting through correspondence.
- Fewer lost tasks.

## Scope

### MVP

- Telegram Integration
- AI Analysis
- Work Item Detection
- Approval Workflow
- Kanban Board
- Evaluation Dataset
- Audit Log

### Future

- Slack Connector
- Email Connector
- WhatsApp Connector
- Decision Detection
- Risk Detection
- Calendar Integration
- Working Days Awareness
- Multi-Team Support

## Non Goals

- Fully autonomous task creation.
- Automatic assignment without user confirmation.
- Multi-tenancy.
- External task management systems.

---

## MVP Acceptance Criteria

> Carried over from the previous design spec (Telegram Task Recognition Bot), aligned with the new model
> (WorkItem instead of TaskCandidate).

The MVP is considered ready when:

1. The system connects to a Telegram chat.
2. The system reads only new messages.
3. `last_synced_at` is saved after a successful run.
4. A repeated sync does not re-read old messages.
5. The system creates Candidates.
6. For candidates, type / assignees / priority / due date are determined when possible.
7. Low confidence is highlighted in the UI.
8. There is a Sync Now button.
9. There is a Last Sync / Sync History screen.
10. There is a Candidates list with a review flow.
11. There is approve / reject / edit.
12. An approved candidate creates a WorkItem on the Kanban board.
13. There is a list of assignees; a Telegram ID can be linked to an assignee.
14. Sync errors are saved and visible.
15. A single `chat_id + external_message_id` does not create duplicates.
