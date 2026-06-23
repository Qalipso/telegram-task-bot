# AI Work Intelligence Platform — Implementation Strategy & Critical Review

- **Status:** Draft for executive approval (CEO / Sr PM / Sr Engineer / Tech Lead)
- **Author role:** Sr PM + Sr TPM + Staff Engineer + CTO (critical review)
- **Inputs treated as requirements, not truth:** `system-spec.md` v1.0, `decisions.md` (D1–D25),
  `reconciliation.md` (40 findings), `database-design.md`, `domain-model.md`, `architecture.md`,
  `llm-extraction-spec.md`, `evaluation-plan.md`, `test-plan.md`.
- **Team assumed:** 1 Senior Full-stack Engineer · 1 AI Engineer · 1 Product Owner.
- **Headline verdict:** **Go — but only on a much smaller MVP than v1.0 defines, and with the
  accuracy targets reframed as north-stars rather than launch gates.** Details below.

---

## 0. Senior Panel Review — Revisions (v1.1)

> This plan was stress-tested by an adversarial panel of five senior reviewers (skeptical CTO, staff
> engineer, AI lead, delivery TPM, grounding critic). They returned 42 critiques; the valid ones are
> integrated here. **These revisions supersede any conflicting text in Phases 1–12.** The panel
> confirmed the thesis (smaller MVP, human-in-loop) but caught a factual error, internal
> contradictions, and places where the plan silently overrode approved specs. Net: the conclusion
> holds, but the timeline is longer, two dependencies move to week 0, and three items need exec sign-off.

### Critical corrections
1. **Timeline was internally inconsistent.** The Phase 7 phases are sequential on one critical path
   (Foundation 1.5 + Telegram 2 + AI 2.5 + Review 1.5 + Work-Mgmt 1 + Prod-ready 1.5 = **10 weeks**),
   so the "~8–9 weeks build" headline was wrong. **Revised: 10 wk critical-path build (zero buffer) +
   2–3 wk pilot; with realistic 15–20% contingency, ~13–16 weeks to a validated MVP.** AI Pipeline
   re-baselined to **3.5–4 wk** (the 9-step pipeline + 3 resolvers won't fit 2.5), or due-date/priority
   resolvers drop to Should-Have.
2. **The Telegram "Bot API fallback" is illusory — now a week-0 gate.** system-spec §8 chose Telethon
   *because* it reads history (which D2 backfill + the §11 window need); the Bot API cannot retrieve
   prior/group history, so **there is no history-capable Plan B — a ban is project-stopping.** Action:
   a **week-0 spike** (parallel with Foundation) — (a) *written* pilot-team consent to a user account
   reading their chat, and (b) a throwaway Telethon session run ~2 weeks against a real chat without
   FloodWait/ban — **before** committing the build. Session bootstrap is its own ~1-wk item, done first.
3. **The 90/80 reframe is a spec amendment needing sign-off + measurable gates.** Dropping the accuracy
   gate silently overrides `evaluation-plan.md`'s "Success Criteria for MVP" (Approved; v1.0 governs).
   Get explicit **PO/CEO ratification** (treat like D11–D25). Make gates measurable:
   **precision = approved/(approved+rejected) ≥ ~70%**; a **recall proxy** via seeded known-real tasks
   the reviewer confirms were surfaced; a **minimum candidate volume** so approval-rate can't be gamed;
   and report **window-level precision and recall separately** (not a blended "accuracy"). 90/80 stays
   the eval-set north-star.
4. **Work-item board statuses had a factual error.** `rejected` is a *candidate* status, not a
   `work_items.status`, and Phase 6 vs Phase 10 disagreed. **Revised board = `inbox / in_progress /
   done / cancelled`** (strict subset of the 9 v1.0 statuses). Candidate rejection lives in the review
   queue, not the board.

### Important corrections
5. **Candidate dedup is now an explicit Must-Have task.** MVP ships a **deterministic guard**: do not
   emit a candidate whose `source_message_ids` substantially overlap an existing non-rejected
   candidate/work-item for the same chat (no embeddings, no thresholds). The "merge" action is
   **deferred/new-scope** (not one of §13's three review actions).
6. **RU is the primary language, not an open question.** Declare **RU-primary, EN-secondary**; seed set
   re-weighted to **≥40 RU / 20 EN**, over-weighting "no-task" negatives; **test the OpenAI model's RU
   extraction quality in the week-0 spike**.
7. **Eval is a week-1 hard deliverable, not a parallel afterthought** — it's the instrument the AI build
   is steered by. Budget **labeling separately** from harness-coding; write a **labeling rubric** first;
   bootstrap the seed set from a **historical chat export** before the pilot (doubles as access/consent
   validation). Add a periodic **false-negative sampling pass** (read windows with no candidate) — the
   feedback loop only labels what was surfaced, so it can't measure recall. Drop the "chicken-and-egg"
   framing (D10 resolves it). 50 cases is the spec *floor* — a regression tripwire, not a tuning set.
8. **Use the spec's confidence bands as the main precision lever.** `llm-extraction-spec` defines
   `>0.90 strong / 0.70–0.90 review / <0.70 skip`. Treat the cutoff as a **tunable hyperparameter** in
   the eval harness (plot precision/recall/FP vs. cutoff). Cheapest, most decisive quality knob — was missing.
9. **In-process scheduling still needs durable retries.** Dropping Redis is fine for scale, but §24
   mandates safe retries/partial-failure. **Revised: a Postgres `jobs` table** (`status, attempt_count,
   locked_at`) polled in-process → real bounded retries + a "failed runs" view as the dead-letter
   surface (D14 admin re-run). No Redis; durability is real.
10. **`connector_accounts` and `candidate_assignees` stay in the MVP table set** (tiny, load-bearing for
    credentials_ref / assignee promotion). The schema is **19 tables**, not 18; MVP ships ~11. Real cut
    targets: `message_attachments`, `labels`, `candidate_labels`, `work_item_labels`, `evaluation_cases`.
11. **MVP is a single-admin tool.** With no notifications, an Assignee has no trigger to open the app, so
    the **Assignee role moves to Should-Have** and "assignees see theirs" is dropped from MVP acceptance.
    (Cheapest Beta activation: a Telegram DM on approval — session already exists, though it makes the
    bot non-read-only.)
12. **Ownership single-point-of-failure:** the AI Engineer owns pipeline + resolvers + eval and is named
    on 5 of 11 risks. Have the **Sr Full-stack build the eval-harness scaffold** (so eval truly
    parallelizes), cross-train the AI↔storage seam, and specify the **FastAPI↔worker contract** (the real
    seam; the two-language concern is otherwise **Low**, not Medium).

### Spec deviations requiring explicit executive sign-off
The MVP ships **below v1.0 §25 Definition of Done.** Approving this plan approves these deviations:
**Tags** (§25 "Tags work"), **full 9-status Kanban**, **multi-assignee, multimodal, voice,
notifications, evaluation UI, multi-chat** — all deferred. Two candidate statuses are **not** optional
and remain in MVP: **`needs_review`** (default low-confidence landing) and **`error`** (invalid-JSON
path, per `llm-extraction-spec`); `duplicate` ships only if the dedup guard (item 5) ships. Review-UI
missing-field highlighting binds to `candidates.missing_fields` (D17); `context_summary`/
`context_confidence` (D20) are captured by the AI Pipeline.

### Net revised verdict
**Still GO**, conditioned on: (a) a **week-0 gate** — written Telegram consent + a Telethon
survivability spike + an RU model-quality check, *before* build; (b) **PO/CEO sign-off** on the
accuracy-target reframe and the DoD deviations; (c) a **realistic 13–16-week** timeline to a validated
single-admin MVP. **If the week-0 gate fails → No-Go / re-scope the ingestion approach.**

---

## Phase 1 — Product Understanding

**Product Summary.** A human-in-the-loop layer that reads a team's Telegram work chat, uses an LLM
to surface *candidate* work items (task/request/reminder/idea/knowledge), and lets an admin
approve/edit/reject them into a Kanban board. The bot never auto-creates final items.

**Business Objective.** Stop actionable work from being lost in chat, and cut the manual labor of
transcribing chat into a task tracker — without forcing the team to change how they communicate.

**Target Users.** *Admin* (runs sync, manages people, reviews candidates) and *Assignee* (receives
and updates their items). Realistically the buyer/champion is a team lead or PM drowning in chat.

**MVP Definition (as written in v1.0 §25).** Telegram sync + storage + context builder + AI
candidates + human review + work items + Kanban + assignees + tags + audit + ai_runs logging +
evaluation dataset + Docker. **This is not an MVP — it is a v1 product.** See Phase 10.

**Success Metrics.** v1.0 sets Task Recognition Accuracy > 90% and Context Understanding > 80%.
**These are aspirational, not MVP gates** (Phase 5). The real MVP success metric is behavioral:
*does a pilot team review the candidate queue and approve enough real items that they stop manually
copying tasks?* Proposed MVP gates: ≥1 pilot team uses it daily for 2 weeks; reviewer approves
≥40% of candidates (precision proxy); reviewer reports it caught items they'd have missed (recall
proxy); false-positive rate low enough that review isn't a chore (< ~1 reject per approve).

**Non-goals (confirmed + recommended additions).** v1.0 names: full autonomy, auto-assign without
approval, multi-tenancy, external task systems. **Add to non-goals for MVP:** voice, image/OCR,
document extraction (all of "Content Normalization" beyond text), smart topic segmentation, the
full 9-status Kanban, multi-assignee, and the evaluation *UI*.

---

## Phase 2 — Requirements Audit

### Confirmed Requirements
Telegram read-only sync (scheduled + manual); idempotent message storage; LLM candidate
extraction with per-field confidence; human approve/edit/reject; work items on a board; assignee
list with Telegram-ID/alias matching; audit log; AI-run logging; email+password auth with
admin/assignee roles. These are coherent and mutually consistent after the reconciliation pass.

### Missing Requirements (material gaps)
1. **Work-item lifecycle ownership.** No spec for reassignment, who can change status (only "their
   own" is implied for assignees), what happens to a work item if its source candidate is later
   judged a duplicate, or whether work items are editable after creation.
2. **Candidate mutability post-approval / re-sync collisions.** If a later sync re-surfaces an
   overlapping context window, can it produce a near-duplicate candidate for a task already
   approved? D9 dedups at the message level, not the *task* level. **No semantic dedup is
   specified** — this is a real correctness gap (see Phase 9).
3. **Auth completeness.** No password reset, session expiry/refresh, login rate-limiting, or
   initial-admin bootstrap flow.
4. **Telegram onboarding/auth flow.** MTProto user sessions need phone login + 2FA + session-string
   storage + re-auth on expiry. Not specified; it's real ops work.
5. **Empty/edge content.** "Pure chatter," forwarded messages, edited/deleted Telegram messages,
   media-only messages, bots/system messages — no handling specified.
6. **Notifications.** Assignees have no way to learn they were assigned (v1.0 lists notifications as
   future) — which undercuts the "Assignee" role's value at MVP.
7. **Pagination/scale of the review queue** and **board** (UI) — unspecified.

### Assumptions
- One Telegram chat for MVP (multi-chat is in the schema but not required to validate value).
- The team is small (v1.0: 500 messages/day) — so cost and scale are non-issues at MVP.
- A human reviews every candidate, so sub-perfect AI is acceptable (this is the core safety net).
- The pilot is internal/friendly (tolerant of rough edges).

### Open Questions
- Who is the first customer, and will they tolerate a Telegram *user account* reading their chat?
- Is Russian-language chat in scope? (The team works in RU; extraction quality is language-sensitive
  and the eval set must reflect it.)
- Is there a real second user (Assignee) at MVP, or is it effectively a single-admin tool first?

### Potential Contradictions (mostly resolved in reconciliation, flagged for the build)
- Accuracy targets (90/80) vs. "precision over recall" vs. realistic LLM-on-chat performance.
- "Evaluation dataset exists" as an MVP DoD item vs. the chicken-and-egg of needing shipped data to
  build a meaningful eval set.

---

## Phase 3 — Architecture Review

| Component | Purpose | Dependencies | Complexity | Risks | Alternatives |
|---|---|---|---|---|---|
| **Frontend (Next.js)** | Dashboard, review queue, board, admin | API | Med | Over-building the 9-status board + tags UI before value is proven | Server-rendered minimal UI; even a basic table beats Kanban for MVP |
| **Backend API (FastAPI)** | REST, auth, orchestrates jobs | DB, Redis | Low–Med | Two languages (TS + Py) for one small team | Could collapse to one stack, but Py worker + Telethon makes FastAPI the right call (keep it) |
| **Database (Postgres)** | Source of truth (~18 tables) | — | Med | Schema is large for an MVP; several tables (labels, eval, ai_runs) are not value-critical day 1 | Start with a subset of tables |
| **Queue (Redis + workers)** | Decouple sync/LLM from UI | Redis | Med | Idempotency/retry/dead-letter (D23) must actually be built or you double-process | A single in-process scheduler is enough for 500 msg/day MVP; Redis can wait |
| **Workers (Python)** | Sync, normalize, context, AI, eval | DB, Redis, OpenAI | High | The most logic lives here; this is the real product | — |
| **AI pipeline (OpenAI)** | Classify + extract + resolve | normalized content, assignee list | **High** | Accuracy, prompt drift, cost, segmentation (see Phase 5) | — |
| **Connector layer** | Pluggable sources | Telethon | Med | Abstraction built for 5 connectors but only 1 exists — speculative generality | Build Telegram concretely; extract the interface only when the 2nd source appears (YAGNI) |

**Architecture Risk Assessment**
- **Critical:** AI extraction quality on real (multilingual) chat; Telegram user-session viability
  (ToS/ban + auth ops).
- **High:** Semantic task-level dedup absent; queue idempotency must be correct; MVP scope breadth
  vs. team size.
- **Medium:** Two-language stack overhead; multimodal normalization complexity (if not deferred);
  context segmentation heuristic.
- **Low:** Postgres choice; Docker Compose deploy; cost at 500 msg/day.

**Verdict:** the architecture is *reasonable and not over-engineered in its primitives*, but it is
**over-scoped** (Redis, connector abstraction, multimodal, 18 tables) for what an MVP needs to
prove. Cut first, scale later.

---

## Phase 4 — Data Model Review

| Entity | Purpose | Lifecycle | Dependencies | Future Risk |
|---|---|---|---|---|
| `users` / `assignees` | Auth + ownership | create→active→deactivated | — | `assignees.user_id` nullable FK (D24); keep clean |
| `chats` / `connector_accounts` | Source config + secrets ref | create→active | — | `credentials_ref` secret handling (D21) must be real |
| `messages` (+`message_attachments`) | Raw + normalized store | new→normalized→analyzed | chats | Attachments table is dead weight until multimodal ships — fine to keep empty |
| `sync_states` / `sync_runs` | Resume + audit of sync | per-chat / per-run | chats | `trigger_type='retry'` flow (D14) |
| `candidates` (+`candidate_messages`,`candidate_assignees`,`candidate_labels`) | AI output pre-review | new→needs_review→approved/rejected/duplicate/error | messages, assignees | **Task-level dedup not modeled** — biggest data risk |
| `work_items` (+`work_item_assignees`,`work_item_labels`) | Approved artifacts | inbox→…→archived | candidates | Reasoning/confidence now snapshotted (good); promotion of assignees (D25) must be implemented |
| `labels` | Controlled tag vocab | — | — | Low |
| `ai_runs` | Observability/cost/eval | per call | — | `input_hash` idempotency (D23) is load-bearing for cost + dedup |
| `evaluation_cases` | Quality measurement | — | — | Not value-critical day 1; keep as offline asset |
| `audit_logs` | Compliance/debug | append-only | — | `entity_type` enum (D22); fine |

**ERD Review Summary.** Well-normalized and, post-reconciliation, internally consistent. Two
substantive concerns: (1) **no entity/constraint expresses task-level deduplication** — only message
uniqueness; (2) several tables (`message_attachments`, `labels`, `evaluation_cases`, parts of
`ai_runs`) carry no MVP value and can be created lazily. Indexing is specified on the hot paths
(`messages`, `candidates.status`); add an index on `ai_runs.input_hash` once idempotency lands.
**Recommendation:** the schema is **19 tables**; ship ~11 for the trimmed MVP (users, assignees,
chats, **connector_accounts**, messages, sync_states, sync_runs, candidates, candidate_messages,
**candidate_assignees**, work_items, audit_logs); add the rest per phase. Real cut targets:
`message_attachments`, `labels`, `candidate_labels`, `work_item_labels`, `evaluation_cases`.

---

## Phase 5 — AI System Review (the crux)

This is where the product lives or dies. Treat everything else as plumbing.

| Stage | Failure / Hallucination | Precision risk | Recall risk | Cost risk | Prompt risk |
|---|---|---|---|---|---|
| Context Builder | Wrong window → wrong task | Mixing topics → false tasks | Window too small → misses multi-msg tasks | Low | "Topic continuation" is itself an unsolved heuristic |
| Candidate extraction | Invents tasks from chatter | **High** (chat is mostly non-tasks) | Misses implicit asks | Med | Schema drift, JSON validity |
| Assignee resolution | Wrong person assigned | Alias collisions | Unknown → unassigned (acceptable) | Low | Name/alias ambiguity |
| Due-date resolution | "Friday" → wrong date | TZ/relative errors | Misses implicit deadlines | Low | Relative-date reasoning is brittle |
| Priority resolution | Over-flags `critical` | Subjective | — | Low | Calibration |
| Evaluation | Measures the wrong thing | — | — | Eval re-runs add cost | Ground-truth labeling is the bottleneck |

**The central reality check.** Extracting actionable tasks from free-form, multilingual team chat is
**one of the harder LLM-judgment tasks**, because the base rate of "this message is a task" is low
and the boundary is fuzzy. **A 90% Task-Recognition and 80% Context-Understanding target is not a
realistic MVP gate** — it is achievable only after substantial prompt iteration against a
representative labeled set, and even then "90% accuracy" needs a precise definition (precision?
recall? F1? per-field?). Shipping *blocked on* those numbers risks never shipping.

**Why this is OK anyway:** the human-in-the-loop is the safety net. A 70%-precision system with a
fast review UI is *useful on day one* and improves via the feedback loop. **Reframe the targets as
north-stars; gate the MVP on reviewer behavior, not on an accuracy number.**

**Recommended AI Architecture.**
- **Two-call pipeline, text-only for MVP:** (1) cheap *classify* "does this window contain any work
  item?" to suppress the dominant non-task traffic (precision lever); (2) *extract* structured
  fields (Structured Outputs / function-calling for guaranteed-valid JSON) only on positives.
- **Context = fixed window (last ~20 + reply/quote chains), no smart segmentation** for MVP. Add
  segmentation later only if eval shows the fixed window is the bottleneck.
- **Prompt versioning from day one** (`prompt_version` in `ai_runs`) — non-negotiable; it's the only
  way to attribute quality changes.
- **Idempotency via `input_hash`** so re-syncs/retries don't re-bill or duplicate.
- **Defer all multimodal** (OCR/vision/voice/doc). It's a separate subsystem that does not test the
  core hypothesis.

**Recommended Evaluation Strategy.**
- **MVP = a lightweight *offline* harness + a hand-labeled seed set (~50 cases, RU + EN, including
  "no-task" negatives and multi-message cases).** This is must-have *engineering* (you can't tune
  blind) but **not** a user-facing feature.
- Drive the set from real reviewed candidates (approve/edit/reject = free labels) — the feedback loop
  *is* the dataset engine.
- Track precision/recall/FP-rate per `prompt_version`; run before every prompt/model change.
- Defer the evaluation *UI*, model-comparison reports, and cost dashboards to Beta/Production.

---

## Phase 6 — Build Strategy

| Block | Goals | Deliverables | Dependencies | Acceptance Criteria |
|---|---|---|---|---|
| **Foundation** | Repo, CI, Docker, DB, auth | Mono-repo (worker/api/web), Compose, Postgres+Alembic, email+pw auth, admin/assignee roles, test baseline | — | `docker compose up` runs all services; admin can log in; migrations apply clean; green test baseline |
| **Core Infrastructure** | Storage + sync state + run history | `messages`/`sync_states`/`sync_runs` + repos; manual `POST /sync/run`; sync-history view | Foundation | Manual sync persists messages idempotently; re-sync creates no dups; run recorded |
| **Telegram Integration** | Read-only Telegram | Telethon connector, session bootstrap, incremental fetch by `last_external_message_id`, error→`sync_runs.failed` | Core Infra | Reads only-new messages; survives FloodWait/auth errors without crashing |
| **AI Pipeline** | Text → candidates | Context builder (fixed window), classify+extract (Structured Outputs), resolvers (assignee/priority/due), confidence, `ai_runs` logging, `prompt_version` | Storage, assignees | A task message yields a candidate; chatter does not; invalid JSON doesn't break sync; per-field confidence stored |
| **Review System** | Human-in-the-loop | Candidate queue UI, approve/edit/reject, low-confidence highlighting, audit on actions | AI Pipeline | Admin approves→work item created; reject kept in history; edits persisted; every action audited |
| **Work Management** | Track approved work | Work items + minimal board (`inbox / in_progress / done / cancelled`), assignee promotion (D25) | Review | Approved candidate → work item (status=inbox); status changes persist. (Candidate *rejection* lives in the review queue, not the board. MVP is single-admin — see §0.11.) |
| **Evaluation** | Know if AI is good enough | Offline harness + seed set + per-version metrics; "add to eval set" action | AI Pipeline | Harness runs, prints precision/recall/FP per `prompt_version`; regression catchable |
| **Production Readiness** | Ship safely | Scheduler (6h), retries/dead-letter, logging/alerts, secrets, backups, auth hardening | All | Scheduled sync runs unattended for a week; failures visible/recoverable; secrets out of code |

**Deferred to Beta/Production (explicitly cut from MVP):** multimodal normalization (image/OCR,
voice, doc/pptx), tags, full 9-status Kanban, multi-assignee, evaluation UI/reports, notifications,
multi-chat, connector abstraction beyond Telegram, smart topic segmentation.

---

## Phase 7 — Delivery Plan

Team: 1 Sr Full-stack, 1 AI Eng, 1 PO. Estimates are calendar weeks for this team, **trimmed
MVP** (not v1.0-as-written).

| Phase | Tasks | Effort | Dependencies | Risk |
|---|---|---|---|---|
| Foundation | scaffold, Docker, DB+migrations, auth/roles, CI | 1.5 wk | — | Low |
| Core Infra + Telegram | storage, sync state/runs, manual sync, Telethon, session bootstrap | 2 wk | Foundation | **High** (Telegram auth/ToS) |
| AI Pipeline (text) | context builder, classify+extract, resolvers, ai_runs, prompts v1 | 2.5 wk | Storage | **Critical** (quality) |
| Review System | queue UI, approve/edit/reject, audit | 1.5 wk | AI Pipeline | Med |
| Work Management (minimal board) | work items, status, assignee promotion | 1 wk | Review | Low |
| Eval harness + seed set | offline harness, ~50 labeled cases, metrics | 1 wk (parallel, AI Eng) | AI Pipeline | Med |
| Production readiness | scheduler, retries/DLQ, logging, secrets, hardening | 1.5 wk | All | Med |
| Pilot + accuracy iteration | run with a real team, tune prompts against eval | 2–3 wk | All | **Critical** |

**Timelines (realistic, this team):**
- **MVP (trimmed, text-only, pilot-ready):** **10 weeks** critical-path build (sequential spine, zero
  buffer) + **2–3 weeks** pilot/tuning; with a realistic 15–20% contingency, **~13–16 weeks** to a
  validated single-admin MVP. (AI Pipeline re-baselined to 3.5–4 wk — see §0.1.) The earlier "8–9
  weeks" was inconsistent with the WBS and is withdrawn.
- **Beta (add image/doc normalization, tags, fuller board, eval UI, multi-chat, hardening +
  accuracy approaching targets):** +**6–8 weeks** → ~**month 4–5**.
- **Production (voice, scale, monitoring, SLAs, possibly a 2nd connector):** +**8–12 weeks** →
  ~**month 6–7**.
- **v1.0-as-written as the "MVP":** would be ~**4–6 months** before any pilot — which is the core
  scheduling risk this plan exists to prevent.

---

## Phase 8 — Dependency Graph

```text
Database ──► Auth ──► Roles ──► Admin UI
Database ──► Message Storage
Telegram Connector ──► Sync Engine ──► Message Storage
Message Storage ──► Context Builder ──► AI Pipeline (classify → extract → resolvers)
Assignee List ──► AI Pipeline (assignee resolution)
AI Pipeline ──► Candidate Storage ──► Review UI ──► Work Items ──► Board
AI Pipeline ──► ai_runs (logging) ──► Evaluation Harness
Review actions (approve/edit/reject) ──► Audit Log
Review actions ──► Evaluation dataset (feedback loop)
Scheduler ──► Sync Engine        Queue/Retry ──► Sync + AI jobs (Production)
```

Critical path: **Database → Storage → Telegram/Sync → Context → AI Pipeline → Review → Work Items.**
Everything else (eval, board polish, tags, multimodal) hangs off this spine and can lag.

---

## Phase 9 — Risk Register

| Risk | Impact | Probability | Mitigation | Owner |
|---|---|---|---|---|
| AI task-detection quality below useful threshold | Critical | High | Human-in-loop safety net; classify-then-extract; eval-driven prompt iteration; gate on reviewer behavior not on 90% | AI Eng |
| Telegram user-session ban / ToS / auth ops | Critical | Med | Dedicated account, conservative rate limits, secure session storage, re-auth runbook. **No history-capable fallback exists** (Bot API can't read prior/group history — §0.2), so a ban is project-stopping → de-risk in a **week-0 spike** + written consent before build | Sr Eng |
| Incorrect / duplicate task detection (no task-level dedup) | High | High | Add similarity-based dedup (title/assignee/window) before insert; mark `duplicate`; review-queue merge | AI Eng |
| Due-date extraction errors (relative dates, TZ) | High | High | UTC anchoring, low-confidence highlighting, always human-confirmed, eval cases for relative dates | AI Eng |
| Context-window failures (wrong/mixed topic) | High | Med | Fixed window + reply chains for MVP; eval the window; defer segmentation | AI Eng |
| MVP over-scope → never ships | High | High | Cut to text-only spine (Phase 10); time-box pilot | PO |
| Cost overruns | Low | Low | 500 msg/day is tiny; `input_hash` idempotency; classify gate; cap eval re-runs | AI Eng |
| Scaling beyond pilot (multi-chat/team) | Med | Low (MVP) | Defer; schema already supports; revisit at Beta | Sr Eng |
| Data loss / partial failure | Med | Med | Storage decoupled from detection; idempotent inserts; retries/DLQ; DB backups | Sr Eng |
| Two-language stack slows a 3-person team | Med | Med | Keep boundaries thin; one owner per stack; minimal BFF | Sr Eng |
| Prompt drift / unattributable regressions | Med | Med | `prompt_version` + eval before every change | AI Eng |

---

## Phase 10 — MVP Cut Analysis (ruthless)

| Tier | Items |
|---|---|
| **Must Have** | Telegram **text** sync (manual + scheduled); idempotent storage; classify+extract → candidates (text only); confidence; assignee resolution from a managed list; **review queue with approve/edit/reject**; work items with a **minimal board** (`inbox / in_progress / done / cancelled`); audit log; `ai_runs` logging + `prompt_version`; **offline eval harness + seed set**; email+pw auth/roles; Docker. |
| **Should Have** | Due-date + priority resolution (can launch with them low-confidence/optional); sync-history screen; basic dashboard counts. |
| **Could Have** | Tags; full 9-status Kanban; multi-assignee; image/OCR + document normalization; evaluation UI/reports; notifications; multi-chat. |
| **Not Needed Yet** | Voice transcription; connector abstraction for Slack/Email/WhatsApp/Discord; decision/risk detection; knowledge graph; multi-tenancy; calendar/working-day awareness. |

**Smallest value-validating MVP:** *One Telegram chat → text-only AI candidate detection → fast
human review → a simple work-item list.* If a pilot team will review that queue and prefer it to
manual copying, the hypothesis is proven. Everything else is scaling a validated idea.

---

## Phase 11 — Technical Debt Forecast

**3 months:** prompt sprawl without enough eval coverage; the fixed context window proving too crude
for multi-message threads; ad-hoc dedup hacks; UI built around 9 statuses/tags that aren't used yet.

**6 months:** likely **AI pipeline refactor** (introduce real classify/extract separation,
segmentation, maybe per-field models or retrieval); **schema migrations** to add task-level dedup
keys and multimodal attachment fields in earnest; connector interface finally earning its
abstraction as a 2nd source appears; eval moving from offline script to a service.

**12 months:** multi-tenancy/scale pressure (per-tenant isolation, rate limits, per-chat scheduling);
moving sync from a single worker to a real queue topology; possible move off Telethon user-sessions
to official Bot API + a compliant ingestion path; cost/observability maturing into dashboards.

Likely rewrites: the **Context Builder** (crude → segmented/retrieval) and the **scheduling/queue**
layer (in-process → distributed). Most else evolves additively.

---

## Phase 12 — Final CTO Recommendation

**Executive Summary.** The product hypothesis is sound and the human-in-the-loop framing de-risks
the AI. The documentation is unusually thorough and now internally consistent. The two things that
will determine success are (1) **shipping a drastically smaller MVP** than v1.0 defines, and (2)
**not gating launch on the 90/80 accuracy numbers**, which are unrealistic as entry criteria.
**Go — with a re-scoped MVP and reframed success metrics.**

**What Is Strong.** Human-in-the-loop (candidates, not auto-tasks); precision-over-recall instinct;
storage decoupled from AI (failure isolation); audit + ai_runs observability designed in; a real
evaluation mindset; clean, normalized schema; a ratified decision log.

**What Is Weak.** MVP scope is a v1, not an MVP; accuracy targets as gates; no task-level dedup;
multimodal treated as in-scope; context segmentation hand-waved; Telegram user-session
operational/compliance risk under-acknowledged; assignee notifications absent (hurts the Assignee
role); two-language stack for a 3-person team.

**Top 10 Risks.** (1) AI quality below useful bar; (2) Telegram session ban/auth ops; (3) MVP
over-scope → no ship; (4) duplicate task detection; (5) due-date errors; (6) context failures;
(7) prompt drift; (8) partial-failure/data integrity; (9) two-stack drag; (10) building UI/eval
features before value is proven.

**Top 10 Priorities.** (1) Cut MVP to the text-only spine; (2) reframe success metrics to reviewer
behavior; (3) classify-then-extract with Structured Outputs; (4) prompt versioning + offline eval
from day one; (5) Telegram session bootstrap + error handling; (6) idempotent storage + `input_hash`;
(7) fast review UI; (8) minimal board; (9) seed eval set (RU+EN, with negatives); (10) pilot with a
real team in week ~9.

**Recommended MVP.** Phase 10 "Must Have" only. One chat, text only, review queue, simple board.

**Recommended Architecture.** Keep FastAPI + Python worker + Postgres + Next.js + Docker.
**Drop for MVP:** Redis/queue (use an in-process scheduler at 500 msg/day), the connector
abstraction (build Telegram concretely), multimodal normalization, and ~8 of the 18 tables.
Add them back at Beta when scale/scope demands.

**Recommended Team Structure.** Sr Full-stack owns Foundation/Storage/Telegram/Review/Board +
deploy. AI Eng owns Context/Extraction/Resolvers/Eval and is the quality owner. PO owns the pilot,
the labeled eval set, and ruthless scope control. Pair on the AI↔storage seam.

**Recommended Build Order.** Foundation → Core Infra + Telegram → AI Pipeline (text) → Review →
minimal Work Management → Eval harness (parallel) → Production readiness → Pilot + tuning.

**Expected Timeline.** Trimmed MVP pilot-ready in **~10–12 weeks**; Beta ~**month 4–5**; Production
~**month 6–7**. v1.0-as-written would be ~4–6 months to first pilot — don't.

**Expected Cost.** Dominated by **team time**, not infrastructure. LLM/API + hosting at 500 msg/day
pilot scale is negligible (low tens of dollars/month); eval re-runs are the only variable, and
small. Budget for the 3-person team over ~3 months to MVP.

**Go / No-Go.** **GO** — conditional on: (a) re-scoping to the text-only MVP; (b) reframing the
90/80 targets as north-stars, gating launch on reviewer behavior; (c) confirming a pilot team that
accepts a Telegram user account reading their chat. If (c) cannot be secured, **pause** — the
ingestion assumption is the riskiest external dependency and should be validated before build.
