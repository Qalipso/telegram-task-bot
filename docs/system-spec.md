# AI Work Intelligence Platform — Final System Specification

- **Version:** 1.0
- **Status:** Approved for MVP Development
- **Role:** Authoritative top-level specification. The other documents in `docs/` (Product Brief,
  Domain Model, Architecture, Database Design, LLM Extraction Spec, Evaluation Plan, Test Plan,
  Decisions) are detailed companions and must remain consistent with this document.
- **Language:** English is canonical (`system-spec.md`); a Russian copy is maintained at
  `system-spec.ru.md`.

## 1. Product Overview

AI Work Intelligence Platform is an internal work management system that automatically analyzes
Telegram conversations, identifies actionable work items, and converts them into structured
workflow objects through a human approval process.

The platform acts as an intelligent layer between team communication and task execution.

Core principle:

```text
Telegram Discussions
→ Context Understanding
→ AI Candidate Generation
→ Human Review
→ Work Item Creation
→ Kanban Workflow
```

The system prioritizes **precision over recall**. False positives are considered more harmful than
missed low-confidence work items.

## 2. Product Goals

### Primary Goals
- Prevent loss of tasks hidden in chat conversations
- Reduce manual extraction of work from Telegram
- Preserve discussion context
- Create a structured workflow from unstructured communication
- Build a reusable dataset for AI evaluation and continuous improvement

### Success Metrics
- Task Recognition Accuracy: `> 90%`
- Context Understanding Accuracy: `> 80%`
- All work items remain traceable back to source discussions.

## 3. Scope

### MVP Scope
- **Communication Source:** Telegram
- **Work Item Types:** Task, Request, Reminder, Idea, Knowledge
- **Workflow:** Human approval required for every AI-generated candidate.
- **Board:** Built-in Kanban board.
- **AI:** OpenAI models.
- **Roles:** Admin, Assignee
- **Evaluation:** Built-in evaluation dataset and regression testing foundation.

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

- **Message** — raw communication unit from Telegram. Can originate from: Text, Image, Voice, Document.
- **Candidate** — AI-generated suggestion. Not yet approved. Requires human review.
- **Work Item** — approved object used by the team.
- **Context Window** — collection of related messages used for AI reasoning.
- **Assignee** — user that can own work items.

## 6. Work Item Model

Work Item contains:

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

All communication sources implement a common connector interface.

- MVP: `TelegramConnector`
- Future: `SlackConnector`, `EmailConnector`, `WhatsAppConnector`, `DiscordConnector`

Connector responsibilities:
- Fetch messages
- Fetch media
- Normalize sender information
- Normalize metadata

## 8. Telegram Integration

- **Technology:** Telethon
- **Reason:** Provides access to Telegram history and advanced synchronization capabilities.

### Sync Modes
- **Scheduled** — every 6 hours.
- **Manual** — admin-triggered sync.

## 9. Message Processing

### Supported Inputs
- **Text** — processed automatically.
- **Image** — processed through OCR and vision analysis.
- **Document** — supported: `pdf`, `docx`, `xlsx`, `pptx`. Text extracted automatically.
- **Voice** — **not processed automatically.** Admin may manually trigger transcription.

## 10. Content Normalization

All inputs become **Normalized Content**:

```text
Text   → normalized text
Image  → OCR text + vision summary
PDF    → extracted text
Voice  → transcript
```

The AI pipeline only consumes normalized content.

## 11. Context Builder

- **Context Source:** messages stored in database.
- **Base Window:** 20 messages.

### Included Context
- Related messages
- Reply chains
- Quoted messages
- Sender metadata
- UTC timestamp
- Assignee list

### Topic Continuation Logic
- If discussion continues: extend context.
- If new discussion detected: start new context.

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
- Only existing assignees
- Multiple assignees allowed
- Unknown assignees not created automatically
- Ambiguous assignments require review

### Due Date Resolution
- Timezone = UTC
- Relative dates converted into calendar dates
- Ambiguous dates marked low confidence
- Missing due date allowed

## 13. Candidate Review System

Every AI result creates a **Candidate**, not a **Work Item**.

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
- **Rejection Flow:** Candidate → Rejected. Rejected candidates remain in history.

## 14. Kanban Board

Statuses:
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

- MVP: free status transitions.
- Future: controlled workflow rules.

## 15. Tags System

MVP includes tags. Examples:
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

Tags can be attached to: Candidates, Work Items.

Used for: filtering, search, reporting.

## 16. Evaluation System

**Purpose:** measure AI quality.

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
Contains:
```text
Input
Expected Output
Actual Output
Result
Model
Prompt Version
```

### Reports
Show: Pass Rate, Fail Rate, Partial Rate, Accuracy per field, Cost, Tokens, Model comparison.

## 17. AI Observability

Every AI call must store:
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

Used for: debugging, evaluation, cost analysis, regression testing.

## 18. Audit System

All critical actions are logged. Examples:
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

Main entities:
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
- Secrets stored outside source code.

Required secrets:
```text
Telegram Credentials
OpenAI API Key
Database URL
```

## 23. Deployment

Architecture:
```text
Frontend (Next.js)
Backend (FastAPI)
Worker (Python)
PostgreSQL
Redis
```

- **Deployment Method:** Docker Compose
- MVP uses local file storage. No S3 integration required.

## 24. Non-Functional Requirements

### Reliability
- No duplicate messages
- Safe retries
- Partial failure support

### Performance
- Handle 500 messages/day
- Batch processing
- Async jobs

### Maintainability
- Connector abstraction
- Prompt versioning
- Auditability

### Observability
- Sync logs
- AI logs
- Evaluation reports

## 25. MVP Definition of Done

System is considered MVP complete when:
- Telegram sync works
- Messages are stored
- Context Builder works
- AI generates candidates
- Human review works
- Work Items are created
- Kanban board works
- Assignees work
- Tags work
- Audit logs work
- AI runs are logged
- Evaluation dataset exists
- Docker deployment works

Resulting workflow:
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
