# Product Brief

> Документ 1 из набора документации **AI Work Intelligence Platform**.
> Каноничная версия — английская (`product-brief.md`); это поддерживаемая русская копия.

## Product Name

AI Work Intelligence Platform

## Vision

Создать внутреннюю систему, которая автоматически превращает рабочие обсуждения в
структурированные рабочие элементы без необходимости вручную переносить информацию из Telegram.

Система должна помогать команде фиксировать задачи, просьбы, напоминания и идеи, сохраняя контекст
принятия решений и снижая вероятность потери важных договорённостей.

## Problem

Основная рабочая коммуникация происходит в Telegram.

В процессе обсуждений регулярно появляются:

- задачи
- просьбы
- напоминания
- идеи

Эти элементы теряются внутри потока сообщений и требуют ручного переноса в систему управления
задачами.

В результате:

- задачи забываются
- контекст теряется
- менеджеры тратят время на ручной разбор переписки

## Target Users

**Admin** — управляет системой, подтверждает найденные элементы, управляет исполнителями.

**Assignee** — получает рабочие элементы и управляет их статусами.

## Success Metrics

- Task Recognition Accuracy > 90%
- Context Understanding Accuracy > 80%
- Снижение ручного разбора переписки.
- Уменьшение количества потерянных задач.

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

- Полностью автономное создание задач.
- Автоматическое назначение без подтверждения пользователя.
- Мультиарендность.
- Внешние task management системы.

---

## Критерии приёмки MVP

> Перенесено из прежней дизайн-спеки (Telegram Task Recognition Bot), приведено к новой модели
> (WorkItem вместо TaskCandidate).

MVP считается готовым, если:

1. Система подключается к Telegram-чату.
2. Система читает только новые сообщения.
3. `last_synced_at` сохраняется после успешного запуска.
4. Повторный sync не перечитывает старые сообщения.
5. Система создаёт Candidates.
6. Для кандидатов определяются type / assignees / priority / due date, когда возможно.
7. Низкая уверенность подсвечивается в UI.
8. Есть кнопка Sync Now.
9. Есть экран Last Sync / Sync History.
10. Есть список Candidates с review-flow.
11. Есть approve / reject / edit.
12. Approved candidate создаёт WorkItem на Kanban-доске.
13. Есть список assignees; Telegram ID можно связать с assignee.
14. Ошибки sync сохраняются и видны.
15. Один `chat_id + external_message_id` не создаёт дубликаты.
