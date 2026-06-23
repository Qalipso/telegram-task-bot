# Test Plan

> Документ 7 из набора документации **AI Work Intelligence Platform**.
> Каноничная версия — английская (`test-plan.md`); это поддерживаемая русская копия.

## Purpose

Test Plan описывает проверки для MVP системы AI Work Intelligence Platform. Цель — убедиться, что
Telegram-синхронизация, AI-анализ, review-flow, Kanban board, users, assignees, audit и evaluation
работают надёжно.

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

1. Manual sync запускается из UI.
2. Scheduled sync запускается по расписанию.
3. Sync читает только сообщения после последней успешной синхронизации.
4. Sync сохраняет `last_synced_at`.
5. Sync сохраняет `last_external_message_id`.
6. Повторный sync не создаёт дубли сообщений.
7. Ошибка Telegram API сохраняется в `sync_runs`.
8. Partial sync не ломает систему.
9. SyncRun содержит количество прочитанных сообщений.
10. SyncRun содержит количество созданных candidates.

## Message Storage Tests

11. Текстовое сообщение сохраняется.
12. Сообщение с вложением сохраняется.
13. Telegram message ID сохраняется.
14. Sender ID сохраняется.
15. Raw payload сохраняется.
16. Уникальность `chat_id + external_message_id` соблюдается.
17. Сообщение получает корректный `processing_status`.
18. Пустое сообщение корректно пропускается.

## Content Normalization Tests

19. Текст сохраняется как `normalized_content`.
20. Голосовое сообщение не транскрибируется автоматически.
21. Голосовое сообщение транскрибируется после ручного действия админа.
22. Изображение отправляется на vision-анализ.
23. Документ отправляется на извлечение текста.
24. Ошибка обработки файла сохраняется.
25. Normalized content доступен для AI pipeline.

## Context Builder Tests

26. Context window берётся из сохранённых сообщений в БД.
27. Context window включает до 20 сообщений.
28. Context builder учитывает reply chain.
29. Context builder учитывает quoted messages.
30. Context builder не смешивает разные темы.
31. Context builder расширяет контекст, если тема продолжается.
32. Context confidence сохраняется.

## AI Pipeline Tests

33. AI создаёт candidate для рабочей задачи.
34. AI не создаёт candidate для обычной переписки.
35. AI классифицирует task.
36. AI классифицирует request.
37. AI классифицирует reminder.
38. AI классифицирует idea.
39. AI классифицирует knowledge.
40. AI выбирает priority из допустимого списка.
41. AI допускает `priority = null`.
42. AI выбирает несколько assignees.
43. AI не создаёт нового assignee.
44. AI возвращает due_date в календарном формате.
45. AI допускает `due_date = null`.
46. AI сохраняет `reasoning_summary`.
47. AI сохраняет confidence по каждому полю.
48. Невалидный JSON не ломает sync.
49. Ошибка модели сохраняется в `ai_runs`.
50. AI run сохраняет model, prompt_version, tokens и cost.

## Candidate Review Tests

51. Candidate создаётся со статусом `new`.
52. Candidate с низкой уверенностью получает `needs_review`.
53. Admin может отредактировать candidate.
54. Admin может approve candidate.
55. Admin может reject candidate.
56. Approved candidate создаёт WorkItem.
57. Rejected candidate сохраняется в истории.
58. Edited candidate сохраняет изменённые поля.
59. Candidate связан с source messages.
60. Candidate может иметь несколько assignees.

## Work Item Tests

61. WorkItem создаётся только после approval.
62. WorkItem получает статус `inbox`.
63. WorkItem сохраняет `source_candidate_id`.
64. WorkItem сохраняет type.
65. WorkItem сохраняет title.
66. WorkItem сохраняет summary.
67. WorkItem сохраняет priority.
68. WorkItem сохраняет due_date.
69. WorkItem сохраняет assignees.
70. WorkItem можно перевести в другой статус.

## Kanban Board Tests

71. Board показывает статусы: Inbox, Backlog, Ready, In Progress, Blocked, Review, Done,
    Cancelled, Archived.
72. Пользователь может менять статус WorkItem.
73. WorkItem отображается в правильной колонке.
74. Cancelled WorkItem не удаляется.
75. Archived WorkItem остаётся доступным в истории.
76. Исполнитель видит назначенные WorkItems.

## Assignee Tests

77. Admin может создать assignee.
78. Admin может указать Telegram ID.
79. Admin может указать Telegram username.
80. Admin может добавить aliases.
81. Admin может отключить assignee.
82. AI resolver использует только активных assignees.
83. При неоднозначном assignee candidate требует выбора.

## User Role Tests

84. Admin видит Sync controls.
85. Admin видит Responsible management.
86. Admin может approve/reject candidates.
87. Assignee не может запускать sync.
88. Assignee не может управлять списком исполнителей.
89. Assignee может менять статус своих WorkItems.

## Audit Tests

90. Approval записывается в `audit_logs`.
91. Rejection записывается в `audit_logs`.
92. Manual edit записывается в `audit_logs`.
93. Status change записывается в `audit_logs`.
94. Sync start записывается в `audit_logs`.
95. Sync finish записывается в `audit_logs`.

## Evaluation Tests

96. Можно создать EvaluationCase.
97. EvaluationCase хранит `expected_output`.
98. EvaluationCase хранит `actual_output`.
99. EvaluationCase получает result `pass/fail/partial`.
100. Evaluation report показывает pass rate.
101. Evaluation report показывает field-level accuracy.
102. Prompt version сохраняется.
103. Model version сохраняется.

## Error Handling Tests

104. Telegram timeout не ломает приложение.
105. LLM timeout не ломает sync.
106. Ошибка OCR не ломает message processing.
107. Ошибка document extraction не ломает batch.
108. Повторный retry не создаёт дубликаты.
109. Failed message можно обработать повторно.
110. Failed AI run можно перезапустить.
