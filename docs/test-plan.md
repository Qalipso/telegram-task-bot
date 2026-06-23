# Test Plan

> Document 7 in the **AI Work Intelligence Platform** documentation set.
> This English version (`test-plan.md`) is the canonical one; the Russian copy (`test-plan.ru.md`) is maintained alongside it.

## Purpose

The Test Plan describes the checks for the MVP of the AI Work Intelligence Platform. The goal is to confirm that
Telegram synchronization, AI analysis, the review flow, the Kanban board, users, assignees, audit, and evaluation
work reliably.

## Test Categories

- Sync Tests
- Message Storage Tests
- Content Normalization Tests
- Context Builder Tests
- AI Pipeline Tests
- Candidate Review Tests
- Work Item Tests
- Kanban Board Tests
- Assignee Tests
- User Role Tests
- Audit Tests
- Evaluation Tests
- Error Handling Tests

## Sync Tests

1. Manual sync is triggered from the UI.
2. Scheduled sync runs on a schedule.
3. Sync reads only messages received after the last successful synchronization.
4. Sync stores `last_synced_at`.
5. Sync stores `last_external_message_id`.
6. A repeated sync does not create duplicate messages.
7. A Telegram API error is recorded in `sync_runs`.
8. A partial sync does not break the system.
9. SyncRun records the number of messages read.
10. SyncRun records the number of candidates created.

## Message Storage Tests

11. A text message is stored.
12. A message with an attachment is stored.
13. The Telegram message ID is stored.
14. The sender ID is stored.
15. The raw payload is stored.
16. Uniqueness of `chat_id + external_message_id` is enforced.
17. A message receives the correct `processing_status`.
18. An empty message is correctly skipped.

## Content Normalization Tests

19. Text is stored as `normalized_content`.
20. A voice message is not transcribed automatically.
21. A voice message is transcribed after a manual action by an admin.
22. An image is sent for vision analysis.
23. A document is sent for text extraction.
24. A file-processing error is stored.
25. Normalized content is available to the AI pipeline.

## Context Builder Tests

26. The context window is built from the messages stored in the database.
27. The context window includes up to 20 messages.
28. The context builder takes the reply chain into account.
29. The context builder takes quoted messages into account.
30. The context builder does not mix different topics.
31. The context builder expands the context when a topic continues.
32. The context confidence is stored.

## AI Pipeline Tests

33. The AI creates a candidate for a work task.
34. The AI does not create a candidate for ordinary conversation.
35. The AI classifies a task.
36. The AI classifies a request.
37. The AI classifies a reminder.
38. The AI classifies an idea.
39. The AI classifies knowledge.
40. The AI selects a priority from the allowed list.
41. The AI permits `priority = null`.
42. The AI selects multiple assignees.
43. The AI does not create a new assignee.
44. The AI returns due_date in calendar format.
45. The AI permits `due_date = null`.
46. The AI stores `reasoning_summary`.
47. The AI stores a confidence value for each field.
48. Invalid JSON does not break sync.
49. A model error is recorded in `ai_runs`.
50. The AI run stores model, prompt_version, tokens, and cost.

## Candidate Review Tests

51. A candidate is created with status `new`.
52. A low-confidence candidate receives `needs_review`.
53. An admin can edit a candidate.
54. An admin can approve a candidate.
55. An admin can reject a candidate.
56. An approved candidate creates a WorkItem.
57. A rejected candidate is kept in the history.
58. An edited candidate keeps the modified fields.
59. A candidate is linked to its source messages.
60. A candidate can have multiple assignees.

## Work Item Tests

61. A WorkItem is created only after approval.
62. A WorkItem receives status `inbox`.
63. A WorkItem stores `source_candidate_id`.
64. A WorkItem stores type.
65. A WorkItem stores title.
66. A WorkItem stores summary.
67. A WorkItem stores priority.
68. A WorkItem stores due_date.
69. A WorkItem stores assignees.
70. A WorkItem can be moved to another status.

## Kanban Board Tests

71. The board shows the statuses: Inbox, Backlog, Ready, In Progress, Blocked, Review, Done,
    Cancelled, Archived.
72. A user can change a WorkItem's status.
73. A WorkItem is displayed in the correct column.
74. A Cancelled WorkItem is not deleted.
75. An Archived WorkItem remains accessible in the history.
76. The assignee sees the WorkItems assigned to them.

## Assignee Tests

77. An admin can create an assignee.
78. An admin can specify a Telegram ID.
79. An admin can specify a Telegram username.
80. An admin can add aliases.
81. An admin can deactivate an assignee.
82. The AI resolver uses only active assignees.
83. When the assignee is ambiguous, the candidate requires a selection.

## User Role Tests

84. An admin sees the Sync controls.
85. An admin sees Responsible management.
86. An admin can approve/reject candidates.
87. An assignee cannot trigger sync.
88. An assignee cannot manage the list of assignees.
89. An assignee can change the status of their own WorkItems.

## Audit Tests

90. An approval is recorded in `audit_logs`.
91. A rejection is recorded in `audit_logs`.
92. A manual edit is recorded in `audit_logs`.
93. A status change is recorded in `audit_logs`.
94. A sync start is recorded in `audit_logs`.
95. A sync finish is recorded in `audit_logs`.

## Evaluation Tests

96. An EvaluationCase can be created.
97. An EvaluationCase stores `expected_output`.
98. An EvaluationCase stores `actual_output`.
99. An EvaluationCase receives a result of `pass/fail/partial`.
100. The evaluation report shows the pass rate.
101. The evaluation report shows field-level accuracy.
102. The prompt version is stored.
103. The model version is stored.

## Error Handling Tests

104. A Telegram timeout does not break the application.
105. An LLM timeout does not break sync.
106. An OCR error does not break message processing.
107. A document-extraction error does not break the batch.
108. A repeated retry does not create duplicates.
109. A failed message can be reprocessed.
110. A failed AI run can be restarted.
