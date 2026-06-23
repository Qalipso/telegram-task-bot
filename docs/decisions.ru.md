# Design Decisions (D1–D25)

> Документ из набора документации **AI Work Intelligence Platform**.
> Каноничная версия — английская (`decisions.md`); это поддерживаемая русская копия.
>
> **Статус:** D1–D10 подтверждены; **D11–D25 + master-таблица labels ратифицированы (Accepted) 2026-06-23**
> (резолюции из отчёта о сверке; отражены в Database Design и LLM Extraction Spec).
>
> **Слито из прежней дизайн-спеки** «2026-06-23 Telegram Task Recognition Bot Design», которая
> выведена из обращения (merge then retire). Здесь зафиксированы решения и их актуальный статус
> относительно новой модели AI Work Intelligence Platform.

| ID | Вопрос | Решение / статус |
|----|--------|------------------|
| D1 | Владелец API | **Актуально.** FastAPI владеет логикой данных/LLM (общие SQLAlchemy-модели с worker); Next.js — UI + тонкий прокси. |
| D2 | Объём backfill при первом sync | **Актуально.** Настраиваемый `initial_lookback` (последние N дней), не вся история. |
| D3 | Тир модели LLM | **Актуально.** Провайдер AI = **OpenAI models** (по system-spec v1.0 §3 и §22); прежнее значение по умолчанию `claude-opus-4-8` отменено. Более дешёвый тир — рычаг конфига (`model_name` в `ai_runs`), без автопонижения. |
| D4 | Таймзона и рабочая неделя | **Актуально.** UTC, Пн–Пт (переопределяемо). LLM Extraction Spec подтверждает: текущее время в UTC. |
| D5 | Авторизация UI | **Актуально.** Email + пароль + серверная сессия; соответствует `users.role` (`admin`/`assignee`). |
| D6 | Глубина аудита | **ОТМЕНЕНО / расширено.** Прежнее «только `updated_at`» заменено полноценным `audit_logs` (с `before_value`/`after_value`) — см. Database Design. |
| D7 | Язык документации | **Актуально.** Оба языка; **EN каноничен** (`*.md`), RU — поддерживаемая копия (`*.ru.md`). |
| D8 | Контекстное окно | **Уточнено.** Reply chain + quoted messages + **последние ~20 сообщений** из БД (по LLM Extraction Spec); не смешивать разные темы; расширять назад при продолжении темы. (Прежний вариант «N=10 / 60 мин» заменён значением «20» из актуальной LLM-спеки.) |
| D9 | Multi-message задачи | **Подтверждено и реализовано в схеме.** Анализ окна (chunk); связь кандидата с сообщениями через `candidate_messages.role` (`primary` = anchor, `context`, `supporting`). Дедуп-инвариант — уникальность `chat_id + external_message_id` на уровне `messages`; один approved candidate → один `work_item`. |
| D10 | Цикл обратной связи | **Актуально, формализовано.** Approve / Reject / Edited-then-Approved → Evaluation Dataset; см. LLM Extraction Spec (Human Feedback Loop) и Evaluation Plan. |

## Закрыто при сверке (2026-06-23)

- **Voice transcription:** решено — голос **не** транскрибируется автоматически; только после
  ручного действия админа (`voice.transcribe_manual`). Применено в Architecture (Content Normalization)
  и system-spec §9.
- **Confidence-поля:** решено через **D18** — сохранить `task_confidence` в БД; задокументировать
  маппинг `confidence.item → task_confidence` в LLM Extraction Spec.
- Полный аудит из 40 находок и их резолюции — в отчёте о сверке (`reconciliation.md`).

## New decisions (D11–D25)

> **Статус: Accepted (ратифицировано 2026-06-23).** Эти пробелы дизайна, не закрытые `system-spec.md`
> v1.0, перенесены из отчёта о сверке (§3) и ратифицированы как резолюции ниже; отражены в
> Database Design и LLM Extraction Spec.

| ID | Вопрос | Рекомендуемая резолюция |
|----|--------|-------------------------|
| **D11** | Токен будущих типов: `decision_future`/`risk_future` (БД) vs `decision`/`risk` (LLM/v1.0)? | Использовать **`decision`/`risk`** везде; пометить их зарезервированными/неактивными в комментарии enum БД (убрать `_future`). |
| **D12** | Где живут результаты обратной связи (feedback outcomes)? | Метки eval-датасета (не `candidate.status`); `was_edited` выводится из строки аудита `candidate_edited`. |
| **D13** | `attachment_type` содержит и `image`, и `photo`. | Свести к **`image`** (соответствует `message_type`); убрать `photo`. |
| **D14** | У `sync_runs.trigger_type='retry'` нет порождающего потока. | Сохранить `retry`; добавить однострочный поток: админ перезапускает `failed` sync_run → новый `sync_run` с `trigger_type='retry'`. |
| **D15** | enum `message_attachments.processing_status` не определён. | Определить `new, processing, processed, failed, skipped`. |
| **D16** | Source messages для WorkItem: выводить или денормализовать? | **Выводить** через `source_candidate_id → candidate_messages` для MVP (без таблицы `work_item_messages`). Пересмотреть, если кандидаты станут изменяемыми после approval. |
| **D17** | У LLM `missing_fields` нет хранилища. | Добавить `missing_fields jsonb` (или `text[]`) в `candidates`. |
| **D18** | Именование `confidence.item` (LLM) vs `task_confidence` (БД). | Сохранить `task_confidence` в БД; задокументировать явный маппинг `confidence.item → task_confidence` в LLM-спеке. |
| **D19** | `confidence.assignee` (скаляр) vs `candidate_assignees.confidence` (по строкам). | `confidence.assignee` = общая уверенность разрешения assignee (хранится на `candidates`); `candidate_assignees.confidence` = score по конкретному candidate-assignee. Оба сохраняются, разная семантика. |
| **D20** | Хранение корневых `context_summary`/`context_confidence`. | `context_confidence` → `candidates.context_confidence` (существует); `context_summary` → хранить по проанализированному контекстному окну (добавить колонку на `candidates` для MVP, snapshot). |
| **D21** | Формат `connector_accounts.credentials_ref`. | Это ссылка (не секрет) — имя env-переменной или ключ secret-manager; секрет живёт вне исходников/БД (v1.0 §22). Определить формат ref в DB design. |
| **D22** | Допустимые значения `audit_logs.entity_type`. | Перечислить: `candidate, work_item, assignee, chat, sync_run, message`. |
| **D23** | Идемпотентность/ретрай `ai_runs.input_hash`. | `input_hash` дедуплицирует одинаковые AI-вызовы (при совпадении — skip/возврат из кеша); ретрай очереди = 3× exponential backoff + dead-letter (v1.0 §21). |
| **D24** | Связь `assignees.user_id ↔ users`. | FK → `users.id`, **nullable** (assignee не обязан быть системным логином); один user ↔ максимум один assignee. |
| **D25** | Промоушн assignee Candidate→WorkItem. | При approval копировать `candidate_assignees` → `work_item_assignees` (перенести `is_primary`; убрать `confidence` по строкам). |

Также ратифицировано: master-таблица `labels` (`id, name, color?`), на которую ссылаются
`candidate_labels` и `work_item_labels`, чтобы словарь тегов был контролируемым (вместо свободного
текста). Добавлена в Database Design.
