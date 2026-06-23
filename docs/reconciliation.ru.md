# Отчёт о согласовании

> Документ из набора документации **AI Work Intelligence Platform**.
> Русская копия; канонический английский оригинал — `reconciliation.md`.

## Назначение и приоритет

Этот отчёт фиксирует межъдокументные несоответствия, выявленные автоматизированным аудитом набора
документации (5 измерений, **40 находок, каждая состязательно проверена** для отсева ошибок чтения),
и даёт единственное разрешение для каждой из них.

**Правило приоритета:** где бы один документ ни противоречил другому, **`system-spec.md` (v1.0,
Approved) имеет преимущество**, а разрешение из этого отчёта является авторитетным для всего, что
v1.0 не закрывает. 7 субдокументов — это подробные дополнения; этот отчёт + v1.0 являются источником
истины.

Легенда статусов: **Resolved by v1.0** (применить указанное исправление документа) · **Decision (D11–D25)**
(требует ратификации; дано рекомендуемое разрешение) · **Test gap** (добавить тест-кейсы) · **Cleanup**
(согласование формулировок).

---

## 1. Критические (3) — разрешены v1.0

| ID | Проблема | Разрешение |
|----|-------|------------|
| `enums-candidate-type-members-diverge` | Набор типов кандидата различается (Domain Model опускает `knowledge`; БД добавляет `decision_future`/`risk_future`; LLM использует `decision`/`risk`). | **Имеет преимущество v1.0 §6:** активные типы = `task, request, reminder, idea, knowledge`; будущие = `decision, risk`. **Исправление применено:** Domain Model теперь перечисляет все 5 активных типов. Именование токенов будущих типов → **D11**. |
| `enums-candidate-status-domain-vs-db` | В Domain Model 4 статуса кандидата; БД/LLM/тесты используют 7 (включая `needs_review`, `duplicate`, `error`). | **Имеет преимущество v1.0 §13:** `new, needs_review, edited, approved, rejected, duplicate, error`. **Исправление применено:** Domain Model теперь перечисляет все 7, с однострочной семантикой для `needs_review`/`duplicate`/`error`. |
| `pipeline-test-coverage-voice-transcription-normalization-contradiction` | Architecture нормализует Voice→Transcript автоматически; тесты (20–21) требуют ручного запуска администратором. | **Имеет преимущество v1.0 §9/§10:** голос **не** транскрибируется автоматически; администратор запускает это. **Исправление применено:** раздел Content-Normalization в Architecture теперь утверждает, что отображение Voice→Transcript применяется только после ручного шага `voice.transcribe_manual`. |

## 2. Разрешено v1.0 (применить согласование документов)

| ID | Разрешение |
|----|------------|
| `entity-table-field-workitem-reasoning-missing-column` | v1.0 §6: WorkItem имеет **Reasoning**. Добавить `reasoning` в `work_items`, снимок (snapshot) делается из кандидата при одобрении. |
| `entity-table-field-workitem-confidence-missing-column` | v1.0 §6: WorkItem имеет **Confidence**. Добавить `confidence` в `work_items` (снимок при одобрении). |
| `entity-table-field-workitem-source-messages-no-join` | WorkItem **Source Messages** выводится через `work_items.source_candidate_id → candidate_messages` (кандидат является неизменяемым снимком). Задокументировано; дополнительной таблицы для MVP нет → см. **D16**, если требуется денормализация. |
| `entity-table-field-candidate-type-enum-mismatch` | То же, что и критическая находка по типам — Domain Model согласована с 5 активными типами. |
| `entity-table-field-candidate-status-enum-mismatch` | То же, что и критическая находка по статусам — Domain Model согласована с 7 статусами. |
| `enums-human-feedback-vs-candidate-status` | `approved`/`rejected`/`edited_then_approved` — это **метки оценочного датасета** (Evaluation Plan + LLM Human Feedback Loop + D10), а **не** `candidate.status`. Отредактированный-затем-одобренный кандидат завершается со `status=approved`; правка фиксируется через действие аудита `candidate_edited`. |
| `enums-audit-actions-three-way-mismatch` | Список действий БД `audit_logs` (9 токенов) является **каноническим** (v1.0 §18). Формулировки Domain Model / Architecture согласуются с ним; неопределённая корзина «User Actions» отбрасывается. Отсутствующие тесты → Test gap ниже. |
| `enums-evaluation-result-missing-pending` | Enum БД `pass/fail/partial/pending` является каноническим. Domain Model `EvaluationCase.result` ссылается на него; «pending» = ещё не запущено. Математика отчёта исключает `pending` из показателей. |
| `enums-work-item-vs-candidate-type-knowledge-only` | Это не нарушение: `decision_future`/`risk_future` — это **неактивные зарезервированные** слоты enum (спецификация LLM их никогда не эмитит). Для всех активных типов продвижение candidate→work_item сохраняет тип. Связано с **D11**. |
| `pipeline-test-coverage-context-window-size-exact-vs-approx` | Имеет преимущество v1.0 §11: **базовое окно = 20 сообщений**. Стандартизировать формулировку «20» по всем документам (убрать «~20»/«до 20»). |
| `gaps-security-attachment-storage-backend-undefined` | v1.0 §23: **локальное файловое хранилище** для MVP. `message_attachments.storage_path` = путь внутри сконфигурированного локального каталога; S3 отложен. |

## 3. Новые решения для ратификации (D11–D25)

> Это настоящие пробелы в проектировании, которые v1.0 не закрывает. **Ратифицировано (Accepted)
> 2026-06-23** с резолюциями ниже; зафиксировано в `decisions.md`.

| ID | Вопрос | Рекомендуемое разрешение |
|----|----------|------------------------|
| **D11** | Токен будущего типа: `decision_future`/`risk_future` (БД) против `decision`/`risk` (LLM/v1.0)? | Использовать **`decision`/`risk`** везде; пометить их как зарезервированные/неактивные в комментарии enum БД (убрать `_future`). |
| **D12** | Где живут результаты обратной связи? | Метки оценочного датасета (а не `candidate.status`); `was_edited` выводится из строки аудита `candidate_edited`. |
| **D13** | `attachment_type` имеет одновременно `image` и `photo`. | Свести к **`image`** (соответствует `message_type`); убрать `photo`. |
| **D14** | У `sync_runs.trigger_type='retry'` нет порождающего потока. | Сохранить `retry`; добавить однострочный поток: администратор перезапускает `failed` sync_run → новый `sync_run` с `trigger_type='retry'`. |
| **D15** | Enum `message_attachments.processing_status` не определён. | Определить `new, processing, processed, failed, skipped`. |
| **D16** | Source messages у WorkItem: выводить или денормализовать? | **Выводить** через `source_candidate_id → candidate_messages` для MVP (без таблицы `work_item_messages`). Пересмотреть, если кандидаты станут изменяемыми после одобрения. |
| **D17** | У LLM `missing_fields` нет хранилища. | Добавить `missing_fields jsonb` (или `text[]`) в `candidates`. |
| **D18** | Именование `confidence.item` (LLM) против `task_confidence` (БД). | Сохранить `task_confidence` в БД; задокументировать явное отображение `confidence.item → task_confidence` в спецификации LLM. |
| **D19** | `confidence.assignee` (скаляр) против `candidate_assignees.confidence` (по строкам). | `confidence.assignee` = общая уверенность разрешения исполнителя (хранится в `candidates`); `candidate_assignees.confidence` = оценка по конкретному кандидату-исполнителю. Оба сохраняются, с различной семантикой. |
| **D20** | Хранение корневых `context_summary`/`context_confidence`. | `context_confidence` → `candidates.context_confidence` (существует); `context_summary` → хранить по каждому проанализированному окну контекста (добавить столбец в `candidates` для MVP, со снимком). |
| **D21** | Формат `connector_accounts.credentials_ref`. | Ссылка (а не сам секрет) — имя переменной окружения или ключ менеджера секретов; секрет живёт вне исходного кода/БД (v1.0 §22). Определить формат ссылки в проектировании БД. |
| **D22** | Допустимые значения `audit_logs.entity_type`. | Перечислить: `candidate, work_item, assignee, chat, sync_run, message`. |
| **D23** | Идемпотентность/повтор `ai_runs.input_hash`. | `input_hash` дедуплицирует идентичные вызовы AI (пропустить/вернуть из кэша при совпадении); повтор очереди = 3× экспоненциальная выдержка + dead-letter (v1.0 §21). |
| **D24** | Связь `assignees.user_id ↔ users`. | FK → `users.id`, **nullable** (исполнитель не обязан иметь системный логин); один пользователь ↔ не более одного исполнителя. |
| **D25** | Продвижение исполнителей Candidate→WorkItem. | При одобрении копировать `candidate_assignees` → `work_item_assignees` (перенести `is_primary`; убрать `confidence` по строкам). |

Также открыто (с меньшей срочностью): мастер-таблица `labels` против свободно-текстовых тегов — v1.0 §19
перечисляет только join-таблицы `candidate_labels`/`work_item_labels`. **Рекомендуется:** небольшой мастер
`labels` (`id, name, color?`), на который ссылаются оба join'а, чтобы словарь тегов был контролируемым.
Помечено для подтверждения.

## 4. Пробелы в тестовом покрытии (добавить в Test Plan)

| ID | Добавить |
|----|-----|
| `pipeline-test-coverage-connector-fetchmedia-metadata-untested` | Тесты для `Connector.fetchMedia()` и `fetchMetadata()`. |
| `pipeline-test-coverage-entity-extraction-stage-untested` | Тест для AI-стадии 2 (качество генерации заголовка/резюме). |
| `enums-audit-actions-three-way-mismatch` (tests) | Тесты аудита для `candidate_created`, `assignee_created`, `assignee_updated`. |
| `enums-evaluation-result-missing-pending` (tests) | Тест для оценочного кейса `pending` (ещё не запущен) + как отчёт его считает. |

## 5. Мелкие правки (согласование формулировок, решение не требуется)

| ID | Примечание |
|----|------|
| `entity-table-field-syncrun-fields-naming-drift` | Поля Domain Model `SyncRun` концептуальны; столбцы БД `sync_runs` (`messages_read/saved/failed`, `candidates_created`) являются каноническими. |
| `entity-table-field-evaluationcase-input-field-mapping` / `gaps-security-evaluationcase-fields-vs-table-divergence` | Унифицировать `EvaluationCase` (Domain Model) ↔ `evaluation_cases` (БД) ↔ структуру датасета Evaluation Plan в единый набор полей; столбцы БД канонические. |
| `llm-db-mapping-2-buckets-vs-3-roles` / `gaps-security-context-role-no-llm-output-field` | LLM эмитит `source_message_ids` + `supporting_message_ids`; Context Builder заполняет строки `candidate_messages.role='context'` (сообщения окна контекста, не эмитируемые LLM). Отображение: source→`primary`, supporting→`supporting`, builder→`context`. |
| `llm-db-mapping-root-context-summary-storage` | См. D20. |
| `pipeline-test-coverage-image-normalization-mapping-mismatch` | Стандартизировать формулировку нормализации изображений как «OCR text + vision summary» по всем документам. |
| `enums-sync-trigger-vs-flows` | См. D14. |
| `enums-attachment-processing-status-undefined` | См. D15. |

---

## Сводка

- **Критические:** 3 — все разрешены v1.0; исправления применены к Domain Model и Architecture.
- **Разрешено v1.0:** 11 элементов согласования.
- **Новые решения (D11–D25 + мастер labels):** 16 — **ратифицировано 2026-06-23**, зафиксировано в `decisions.md`.
- **Пробелы в тестах:** 4 набора кейсов для добавления.
- **Мелкие правки:** 6 согласований формулировок.

Отклонено состязательной проверкой: 0 (все 40 находок подтверждены как реальные или частичные).
