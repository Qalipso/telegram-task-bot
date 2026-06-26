# Phase 7 — QA gate (mandatory)

> **Scope of this phase.** This phase implements the design spec's **§12 (Testing strategy)**
> and **§13 (Risks & mitigations)** as an executable, evidence-producing QA gate that runs
> *after* Phases 1–6 have landed. It is the final gate in §14 of the contract
> (`docs/specs/2026-06-26-bot-first-capture-layer-design.md`): **agent = qa-critic (Opus)**,
> gate = **zero unresolved CRITICAL/REQUIRED**.
>
> **This phase writes a QA checklist document — not product code.** The one file it creates is
> `docs/build/bot-first-capture-qa-gate.md` (a stage-report-style verification artifact, in the
> same family as `docs/build/STAGE-16-verification.md`). Every task either (a) runs a command
> against the already-built layer and records the evidence into that doc, or (b) writes a
> checklist section that a human/QA executor fills in. The Iron Law that applies hardest here is
> **§1.3 — no completion claim without fresh verification evidence**: every PASS in the QA doc
> must carry the command that produced it and that command's exit code / output.
>
> **No source code under `api/`, `worker/`, `bot/`, or `core/` is edited in this phase.** If a QA
> step *finds* a defect, this phase records it as a **required-fix** and routes it back to the
> owning phase (1, 2, 3–5, or 6) — it does not fix product code here (surgical-changes /
> one-production-editor, §1.5 + §11.3 of CLAUDE.md). The gate **fails** until those fixes land
> and the gate is re-run.

---

## 0. Orientation for an executor with ZERO context (read this first)

You are verifying the **bot-first Telegram capture & confirm layer** built across Phases 1–6.
Here is the minimum you must know to run this gate. All paths are absolute under
`/Users/eduardshatalov/Documents/telegram-task-bot`.

### 0.1 What the layer is (one paragraph)
A BotFather Bot API bot is the primary capture/confirm surface. Group messages flow
forward-only into a Redis buffer, get drained by the existing `run_sync` path, become
**Candidates** (never auto WorkItems), and the bot DMs an admin a card. A human taps
Approve/Reject/Edit/Assign; the bot **authorizes the tapper itself** before calling the
existing admin-gated API. Account linking is done via a single-use `/link <code>` redeemed at
`POST /api/auth/telegram/redeem`. Precision over recall is preserved: `<0.60` confidence is
dropped, ambiguous assignees downgrade to `needs_review`, and there is **no "Approve all"**.

### 0.2 The contract surfaces Phases 1–6 introduced (you verify these exist and behave)
These are consumed by this gate; do **not** redefine them. Cited from the sibling phase plans
in `docs/specs/impl-plan/` and the design spec.

| Surface | Where it lives | Introduced by | What this gate checks |
|---|---|---|---|
| `Candidate.unresolved_mentions` (nullable JSONB) | `core/.../models.py`; Alembic migration | Phase 1 (Tasks 1.4, 1.5) | column exists; migration up/down clean |
| `_link_assignees` ambiguity fix | `worker/.../extract.py:190` | Phase 1 (Task 1.2) | ambiguous mention → no link, `needs_review` |
| `_set_candidate_assignees` validation | `api/.../routers/candidates.py:49` | Phase 1 (Task 1.x D) | stale/ inactive assignee id → 422 |
| `CandidateOut`: `assignee_count`, `assignee_ambiguous`, `unresolved_mentions`, 4 per-field confidences | `api/.../schemas.py` | Phase 1 (Task 1.7) | fields present in API response |
| `POST /api/auth/telegram-link/start` | `api/.../routers/auth.py` | Phase 2 (Task 2.4) | admin-only (401/403 gates) |
| `POST /api/auth/telegram/redeem` | `api/.../routers/auth.py` + `api/.../telegram_link.py` | Phase 2 (Tasks 2.5–2.9) | single-use, TTL, rate-limit, no client identity, unlinked-refusal |
| `tglink:` Redis prefix + rate-limit prefixes `tglink:rl:tg:` / `tglink:rl:ip:` | `api/.../telegram_link.py` | Phase 2 (Task 2.1) | distinct from `session:` |
| `secure=True` on session cookie | `api/.../routers/auth.py:21` | Phase 2 (Task 2.10) | cookie carries `Secure` |
| `bot/` package + 6th compose service `bot` | `bot/`, `docker-compose.yml` | Phase 3 | imports; boots token-less; no exposed port |
| `aiwip_bot.api_client.ApiClient` (login + cookie replay) | `bot/.../api_client.py` | Phase 3 | `me()` → 200 |
| `aiwip_bot.authz` per-callback tapper authz | `bot/.../authz.py` | Phase 4 | non-admin/unlinked tapper denied |
| `aiwip_bot.cards`, `aiwip_bot.handlers`, `aiwip_bot.digest` | `bot/.../` | Phase 4 | no "Approve all"; `<0.60` never surfaced; one digest per burst |
| `botuser:` / `botcard:` Redis prefixes (prefs/watermark) | `bot/.../state.py` | Phase 4 | `botcard:` watermark prevents re-surfacing (distinct from the intra-cycle `aiwip:botdigest:{chat}` buffer) |
| `aiwip_bot.onboarding` configure-before-capture gate + `aiwip:botcfg:{chat}` | `bot/.../onboarding.py`, `bot/.../ingest.py` | Phase 5 | unconfigured chat captures nothing |
| `BotApiConnector` + `aiwip:botbuf:{chat}` / `aiwip:botlock:{chat}` + `_build_connector` factory + `bot.notify` | `worker/.../connectors/bot_api.py`, `worker/.../consumer.py` | Phase 6 | buffer drained ascending; debounce coalesces; Telethon removed |
| `ConnectorType.telegram_bot` enum value | `core/.../models.py`; Alembic | Phase 6 | enum value present |

### 0.3 The test runner (exactly how to run tests)
- **Test framework:** `pytest`. Config at `/Users/eduardshatalov/Documents/telegram-task-bot/pytest.ini`.
  By the time this gate runs, `testpaths` must read
  `core/tests api/tests worker/tests bot/tests` (Phase 3 Task 3.2 / Phase 5 Task 5.0 add `bot/tests`).
- **Prerequisites:** a reachable **local Postgres** (`aiwip_test` DB) and **local Redis** on
  `localhost`. The repo-root `conftest.py` forces `DATABASE_URL`/`REDIS_URL` to `localhost`
  (`conftest.py:10-11`), so tests hit local services regardless of `.env`.
- **The canonical command (run from repo root):**
  ```
  python -m pytest -q
  ```
  If the venv binary is preferred (as in `STAGE-16-verification.md:23`), the equivalent is
  `./.venv/bin/python -m pytest -q`.
- **Baseline today:** `96 tests collected` (verified 2026-06-26 via `pytest --collect-only -q`).
  After Phases 1–6 add tests, the number is **higher** — the gate asserts **0 failures / exit 0**,
  not an exact count (count is recorded for the record, not asserted equal to 96).

### 0.4 The "stale-image" gotcha (you WILL hit this — read it twice)
Tests import **on-disk source** (`api/src/aiwip_api`, etc.). Docker containers run **source baked
into the image at build time**. They drift. `STAGE-16-verification.md` failed precisely because of
this: 92 tests green, but 8 live endpoints 404 from a stale image. **Every container/live check in
this gate must be preceded by a rebuild** of the affected service:
```
docker compose build <svc> && docker compose up -d <svc>
```
and the gate records the image build timestamp vs the source mtime (the §2 root-cause technique in
`STAGE-16-verification.md`).

### 0.5 The QA artifact this phase produces
Single file: `/Users/eduardshatalov/Documents/telegram-task-bot/docs/build/bot-first-capture-qa-gate.md`.
It mirrors the structure of `docs/build/STAGE-16-verification.md` (FINAL VERDICT → numbered
evidence sections → summary). Tasks 7.1–7.12 build it section by section; Task 7.13 fills the
verdict and the required-fix vs nice-to-have split.

---

## How tasks work in this phase

This phase has no application code to TDD, so the "Red → Green" rhythm is adapted honestly:
- **Red** = run the verification command / open the checklist section and observe the *current*
  (unverified or failing) state — capture the raw output.
- **Green** = the command passes with the expected exit code / the checklist line is satisfied by
  recorded evidence, and that evidence is pasted into the QA doc section.
- **commit** = the per-task Conventional Commit line (commits happen **only when the user asks**).

If any Red does **not** turn Green, the line is recorded as a **REQUIRED-FIX** with the failing
evidence and the owning phase, and the gate stays **FAILED** (Task 7.13). Never paper over a red.

---

## Task 7.1 — Create the QA gate document skeleton

**Goal:** create the single artifact this phase writes, with the section headers the later tasks
fill in. This is the "checklist doc, not product code" deliverable.

**Red — prove the file does not exist yet:**
```
test ! -f /Users/eduardshatalov/Documents/telegram-task-bot/docs/build/bot-first-capture-qa-gate.md && echo ABSENT
```
Expected output: `ABSENT` (exit 0). If it prints nothing, the file already exists — read it first
before overwriting.

**Green — write the skeleton.** Create
`/Users/eduardshatalov/Documents/telegram-task-bot/docs/build/bot-first-capture-qa-gate.md`
with exactly this content:

```markdown
# Bot-First Capture & Confirm Layer — QA Gate (mandatory)

**Date:** <YYYY-MM-DD of the run>
**Branch:** build/v1
**Verifier:** qa-critic (independent, read-only except this doc)
**Scope:** Prove the bot-first capture & confirm layer (design spec
`docs/specs/2026-06-26-bot-first-capture-layer-design.md`, Phases 1–6) satisfies §12 + §13.
**Gate rule:** PASS only when there are **zero unresolved CRITICAL/REQUIRED** findings.

---

## FINAL VERDICT
<filled by Task 7.13 — one of: GATE PASSED / GATE FAILED, with the one-line reason>

---

## 1. Full test suite (§12 baseline)
<Task 7.2>

## 2. Assignee-ambiguity precision fix (§6.1 A, §12)
<Task 7.3>

## 3. Redeem endpoint — dedicated SECURITY re-review (§6.4, §13)
<Task 7.4>

## 4. Per-callback authorization (§6.4, §12)
<Task 7.5>

## 5. BotApiConnector ingestion + debounce (§6.3, §12)
<Task 7.6>

## 6. Confirmation policy — precision over recall, no Approve-all, <0.60 never surfaced (§6.2, §12)
<Task 7.7>

## 7. Configure-before-capture gate (§7)
<Task 7.8>

## 8. Telethon cutover + single-writer (§6.3, §14 Phase 6)
<Task 7.9>

## 9. BotFather privacy-mode-OFF + bot-admin runbook (§6.3, §13)
<Task 7.10>

## 10. Forward-only end-to-end on one real group (§12, §15 MVP)
<Task 7.11>

## 11. Cookie hardening + secrets posture (§6.4, §13)
<Task 7.12>

## 12. Required-fixes vs nice-to-haves
<Task 7.13>

---

## Summary
<Task 7.13>
```

**Verify it exists with the 12 sections:**
```
grep -cE '^## [0-9]+\.' /Users/eduardshatalov/Documents/telegram-task-bot/docs/build/bot-first-capture-qa-gate.md
```
Expected output: `12` (exit 0).

**commit:** `docs: scaffold bot-first capture QA gate document`

---

## Task 7.2 — Section 1: full pytest suite is green (§12 baseline)

**Goal:** §12's hard requirement — "the existing ~94-test suite must stay green throughout" — plus
all the new Phase 1–6 tests. This is the broadest gate; run it first.

**Red — run the full suite fresh and capture exit code:**
```
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest -q; echo "EXIT=$?"
```
Read the **full** tail, not just the last line. Record: passed count, failed count, error count,
warnings, exit code, duration.

**Green criteria (all must hold):**
- `EXIT=0`.
- `0 failed`, `0 errors`.
- passed count **≥ 96** (the pre-Phase-1 baseline; will be higher after Phases 1–6 add tests).
- `bot/tests` were actually collected (proves Phase 3/5 wired `testpaths`):
  ```
  python -m pytest --collect-only -q 2>/dev/null | grep -c '^bot/tests/'
  ```
  Expected: a number **> 0**.

**Record into Section 1** (table format, mirroring `STAGE-16-verification.md` §1):

| Metric | Result |
|---|---|
| Passed | `<n>` |
| Failed | `0` |
| Errors | `0` |
| Exit code | `0` |
| `bot/tests` collected | `<n>` (>0) |

If `EXIT != 0`: paste the failing node ids verbatim, mark Section 1 **FAILED**, and add each
failing test to the Task 7.13 required-fix list with its owning phase. **Do not proceed to
declare the gate passed.**

**commit:** `docs(qa): record full-suite result in QA gate §1`

---

## Task 7.3 — Section 2: assignee-ambiguity precision fix (§6.1 A)

**Goal:** §12's named test — two active "Саша" assignees + a "Саша" mention ⇒ candidate becomes
`needs_review` with **no** primary linked. This is the CRITICAL pre-existing precision bug fixed in
Phase 1. The gate re-runs Phase 1's test as fresh evidence (do not trust the green from Task 7.2
alone; name it explicitly).

**Red/Green — run Phase 1's ambiguity test by name and the whole extract suite:**
```
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest worker/tests/test_extract.py -q -k "ambiguous or needs_review or two_sasha or link_assignees"; echo "EXIT=$?"
```
Expected: at least one test selected and **all selected pass**, `EXIT=0`. If `-k` selects **zero**
tests, the ambiguity test is missing — that is itself a REQUIRED-FIX against Phase 1 (the §12 test
is mandatory). In that case re-run the full extract file to confirm nothing else is red:
```
python -m pytest worker/tests/test_extract.py -q; echo "EXIT=$?"
```

**Independent assertion the fix is real (not just that a test exists)** — confirm the source no
longer links all matches arbitrarily. `worker/.../extract.py:158-161` already downgrades on the
zero-match path; verify the ambiguous (`len>1`) path now also appends `"assignee"` and downgrades:
```
grep -nE "len\(|> 1|needs_review|missing_fields|unresolved_mentions" /Users/eduardshatalov/Documents/telegram-task-bot/worker/src/aiwip_worker/extract.py | sed -n '1,40p'
```
Record the lines that show the ambiguous branch downgrading to `needs_review` and **not** calling
the link-all path.

**Record into Section 2:** the test node id(s) that passed, exit code, and the source-line citation
proving the ambiguous branch downgrades. Verdict PASS/FAIL.

**commit:** `docs(qa): record assignee-ambiguity fix verification in QA gate §2`

---

## Task 7.4 — Section 3: redeem endpoint dedicated SECURITY re-review (§6.4) — the security gate

**Goal:** the single most security-critical surface (a session-minting unauthenticated endpoint).
The brief requires a **dedicated** re-review of `/redeem` covering: single-use, TTL,
rate-limit, no client-supplied identity, and unlinked refusal. This task both (a) re-runs Phase 2's
tests as fresh evidence and (b) runs the repo's security-review skill on the redeem code and folds
the findings in.

**Step 1 — re-run every redeem/link test by name (fresh evidence):**
```
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest api/tests/test_telegram_link.py -q; echo "EXIT=$?"
```
Expected `EXIT=0`. Then confirm each REQUIRED security behavior is covered by a *named* test
(Phase 2's self-review lists these exact names):
```
python -m pytest api/tests/test_telegram_link.py --collect-only -q 2>/dev/null | grep -E "single_use|rate_limit|identity_comes_from_code|refuses_user_without_linked|does_not_autocreate"
```
Expected: a non-empty list that includes **all five** of:
- `test_redeem_is_single_use`
- `test_redeem_rate_limit_trips_per_telegram_user` (and/or per-IP)
- `test_redeem_identity_comes_from_code_not_body`
- `test_redeem_refuses_user_without_linked_assignee`
- `test_redeem_does_not_autocreate_user`

For **any** missing name → REQUIRED-FIX against Phase 2 (the §12 redeem test is mandatory), gate
stays FAILED.

**Step 2 — source-level security re-review (the dedicated gate the brief demands).** Read the two
redeem-owning files in full and confirm each hard requirement from §6.4 against the actual code:
```
sed -n '1,220p' /Users/eduardshatalov/Documents/telegram-task-bot/api/src/aiwip_api/telegram_link.py
grep -nE "redeem|telegram-link|create_session|secure|telegram_user_id|429|400|compare_digest|GETDEL|getdel|EVAL|register_script" /Users/eduardshatalov/Documents/telegram-task-bot/api/src/aiwip_api/routers/auth.py
```
Fill this **security checklist** in Section 3 — each line is PASS only with the file:line citation
that proves it:

- [ ] **Single-use** — the code is consumed atomically (GETDEL / Lua compare-and-delete); a second
      redeem cannot return the user id. *Cite the atomic op.*
- [ ] **Short TTL** — `LINK_CODE_TTL_SECONDS` is small (≈300s) and applied at issue time. *Cite.*
- [ ] **Rate-limited** — per `telegram_user_id` AND per IP, fixed-window counter; trip → **429**.
      *Cite the two prefixes `tglink:rl:tg:` / `tglink:rl:ip:` and the 429 response.*
- [ ] **Never trusts client-supplied `telegram_user_id` as identity** — identity comes from the
      *code → issuing user* binding; the body's `telegram_user_id` is only **written** after the
      code verifies the user, never used to *select* the user. *Cite the redeem handler logic.*
- [ ] **Refuses the unlinked case** — `Assignee.user_id IS NULL` → **400** "ask an admin"; **never**
      auto-creates a User, **never** grants admin. *Cite the 400 branch and the absence of any
      `User(...)` insert or role mutation in the handler.*
- [ ] **No new auth scheme** — the endpoint ends by calling existing `auth.create_session(user.id)`
      so `get_current_user`/`require_admin` keep working. *Cite the `create_session` call.*
- [ ] **constant-time compare posture** — confirm Phase 2's stance (the code IS the Redis key,
      consumed by atomic GETDEL, so there is no app-side byte compare). Phase 2 dependency-note 1
      flags this for *your* decision. **Decide here:** accept the GETDEL posture (record the
      rationale) OR raise a REQUIRED-FIX asking Phase 2 to add an explicit `secrets.compare_digest`
      verifier. State the decision and reasoning in Section 3.
- [ ] **Explicit TTL-expiry test** — Phase 2 dependency-note 2 deferred a literal expiry test as
      flaky. **Decide here:** accept the single-use/unknown-code branch as adequate TTL coverage
      (record rationale) OR raise it as a NICE-TO-HAVE (not a blocker — the TTL is structurally set
      at issue time, already verified above). State the decision.

**Step 3 — run the repo security-review skill on the diff for this layer** (defense in depth beyond
the manual checklist). Invoke `/security-review` (the available skill) scoped to the bot-first
changes; capture any CRITICAL/HIGH finding into Section 3. Triage each finding by §3.6 severity:
**Critical/Required → blocker** (gate FAILED), **Minor → nice-to-have**.

**Record into Section 3:** the test result + exit code, the completed security checklist with
citations, the two recorded decisions (compare_digest, TTL test), and the security-review findings
with severities. **The gate cannot pass with any unresolved CRITICAL/REQUIRED on this endpoint
(§13: "dedicated security review before exposure").**

**commit:** `docs(qa): record /redeem security re-review in QA gate §3`

---

## Task 7.5 — Section 4: per-callback authorization (§6.4)

**Goal:** §12's authz tests — a non-admin / unlinked tapper is denied; a replayed `callback_data`
for an already-approved candidate is a no-op. This proves the bot authorizes the tapper itself
*before* calling the API, and treats `callback_data` as untrusted.

**Step 1 — re-run the bot authz tests by name (fresh evidence):**
```
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest bot/tests/ -q -k "authz or tapper or non_admin or unlinked or replay or callback"; echo "EXIT=$?"
```
Expected: tests selected and all pass, `EXIT=0`. If `-k` selects zero tests → REQUIRED-FIX against
Phase 4 (these are §12-mandatory), and run the whole authz file to be sure:
```
python -m pytest bot/tests/test_authz.py -q; echo "EXIT=$?"
```

**Step 2 — confirm the authz logic at source level** (the spec's lookup chain
`from_user.id → Assignee.telegram_user_id → Assignee.user_id → User.role==admin`):
```
grep -nE "from_user|telegram_user_id|user_id|role|admin|ask an admin|re-?fetch|candidate" /Users/eduardshatalov/Documents/telegram-task-bot/bot/src/aiwip_bot/authz.py
grep -nE "re-?fetch|get_candidate|actionable|status|callback_data|untrusted" /Users/eduardshatalov/Documents/telegram-task-bot/bot/src/aiwip_bot/handlers.py
```
Confirm in Section 4: (a) the tapper is resolved to a `User` and `role==admin` is required; (b) the
handler **re-fetches the candidate by id server-side** and checks it is still actionable, rather
than trusting the action in `callback_data`.

**Record into Section 4:** node ids + exit code; the two source confirmations. PASS only if both the
non-admin/unlinked denial and the replay-no-op are demonstrated by passing tests. Otherwise
REQUIRED-FIX against Phase 4.

**commit:** `docs(qa): record per-callback authz verification in QA gate §4`

---

## Task 7.6 — Section 5: BotApiConnector ingestion + debounce (§6.3)

**Goal:** §12's connector tests — buffer drained in ascending id order; `run_sync` dedup holds;
`messages_saved>0` gate fires; debounce coalesces N messages → 1 job.

**Step 1 — re-run the connector / debounce tests by name:**
```
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest -q -k "bot_api or botbuf or debounce or coalesce or ascending or single_writer or _build_connector"; echo "EXIT=$?"
```
Expected: tests selected (some live in `worker/tests/`, some in `bot/tests/`) and all pass,
`EXIT=0`. If zero selected → REQUIRED-FIX against Phase 6.

**Step 2 — confirm the connector reuses the existing persist path** (no second writer to `Message`):
```
grep -nE "def fetch_messages|botbuf|ascending|sort|min_id|FetchedMessage" /Users/eduardshatalov/Documents/telegram-task-bot/worker/src/aiwip_worker/connectors/bot_api.py
grep -nE "_build_connector|connector_type|telegram_bot|bot.notify|botlock" /Users/eduardshatalov/Documents/telegram-task-bot/worker/src/aiwip_worker/consumer.py
```
Confirm in Section 5: `BotApiConnector.fetch_messages` drains `aiwip:botbuf:{chat}` in **ascending
id order**, and `_build_connector` is a factory keyed on `Chat.connector_type` (so a chat is owned
by exactly one transport — no double-ingest).

**Record into Section 5:** node ids + exit code; the ascending-order and single-transport
confirmations; the debounce-coalesces-to-1-job test result. PASS/FAIL per §12.

**commit:** `docs(qa): record BotApiConnector + debounce verification in QA gate §5`

---

## Task 7.7 — Section 6: confirmation policy — precision over recall (§6.2)

**Goal:** the heart of the product's Iron Laws expressed as testable behavior:
- **`<0.60` is never surfaced** by the bot (it stays dropped at extract time; the bot must not
  resurrect it).
- **No "Approve all"** — a digest batches the *prompt*, but every approval is one tap → one
  `POST /approve`; the bot **never** calls `/approve` itself.
- **Burst of N candidates ⇒ exactly one digest** (debounce + watermark prevent burst spam and
  re-surfacing).

**Step 1 — re-run the confirmation tests by name:**
```
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest bot/tests/ -q -k "digest or one_digest or coalesce or surfaced or below_threshold or low_confidence or approve_all or watermark"; echo "EXIT=$?"
```
Expected: tests selected and all pass, `EXIT=0`. If zero selected → REQUIRED-FIX against Phase 4.

**Step 2 — adversarial source checks (precision-over-recall is a *negative* property; prove the
absence of the dangerous code):**
- Confirm **no "Approve all" affordance** exists anywhere in the bot:
  ```
  grep -rniE "approve.?all|approveall|bulk.?approve" /Users/eduardshatalov/Documents/telegram-task-bot/bot/src
  ```
  Expected: **no matches** (exit 1 from grep). Any match → REQUIRED-FIX (violates §6.2).
- Confirm the bot **never calls `/approve` without a human callback** — every `/approve` call is
  reached only from a callback handler, never from the digest/ingest/poll path:
  ```
  grep -rnE "approve" /Users/eduardshatalov/Documents/telegram-task-bot/bot/src/aiwip_bot/digest.py /Users/eduardshatalov/Documents/telegram-task-bot/bot/src/aiwip_bot/ingest.py
  ```
  Expected: **no `/approve` call** in digest or ingest (those run without a human tap). Any
  auto-approve path → CRITICAL REQUIRED-FIX (breaks Iron Law §1, human-in-the-loop).
- Confirm `<0.60` is never re-surfaced — the band constant `REVIEW_BAND=0.60` is honored and the
  bot reads candidates filtered to actionable statuses only (it does not fetch dropped items):
  ```
  grep -rnE "REVIEW_BAND|0\.60|status=|needs_review|new" /Users/eduardshatalov/Documents/telegram-task-bot/bot/src/aiwip_bot/cards.py /Users/eduardshatalov/Documents/telegram-task-bot/bot/src/aiwip_bot/digest.py
  ```
  Confirm dropped/`<0.60` candidates are never listed (extract.py already skips `<0.60` at
  `_status_for`, `extract.py:49-54`, returning `None` → no Candidate row; the bot reads Candidates,
  so a dropped item has no row to surface — record this structural argument plus the test evidence).
- Confirm the **cross-cycle re-surfacing watermark** exists (the `botcard:` per-chat prefix, design
  §6.2: "The Redis watermark prevents re-surfacing"). The watermark stores the highest
  already-surfaced `candidate_id` per chat (set on emit) and `digest.emit_cycle` / `stage_candidate`
  must **skip ids at-or-below it**, so a candidate staged in two cycles is surfaced **once**:
  ```
  grep -rnE "botcard:|watermark|emit_cycle|stage_candidate|already.?surfaced|candidate_id" /Users/eduardshatalov/Documents/telegram-task-bot/bot/src/aiwip_bot/state.py /Users/eduardshatalov/Documents/telegram-task-bot/bot/src/aiwip_bot/digest.py
  ```
  Expected: the `botcard:` watermark is read in `digest.emit_cycle` (or `stage_candidate`) and
  already-surfaced ids are skipped. This is **distinct from** the intra-cycle `aiwip:botdigest:{chat}`
  coalesce buffer — `botcard:` is the cross-cycle dedup. If `botcard:` is absent or `emit_cycle` has
  no at-or-below-watermark skip (so the same candidate could surface in two cycles) → REQUIRED-FIX
  against Phase 4 (the watermark is load-bearing per §6.2; without it re-surfacing is possible).

**Record into Section 6:** node ids + exit code; the four adversarial-check results (grep outputs,
including the *expected-empty* ones). PASS only if (a) the one-digest-per-burst test passes,
(b) no Approve-all affordance exists, (c) no auto-approve path exists, (d) `<0.60` is structurally
unreachable by the bot, and (e) the `botcard:` cross-cycle watermark is present and consulted on
emit (re-surfacing is prevented).

**commit:** `docs(qa): record confirmation-policy verification in QA gate §6`

---

## Task 7.8 — Section 7: configure-before-capture gate (§7)

**Goal:** §7's onboarding rule — an **unconfigured** chat captures **nothing** (no
`aiwip:botbuf:{chat}` push, no `aiwip:jobs` enqueue); a configured chat captures.

**Step 1 — re-run Phase 5's gate tests by name:**
```
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest bot/tests/ -q -k "onboarding or configure or unconfigured or gate or botcfg or capture"; echo "EXIT=$?"
```
Expected: tests selected and all pass, `EXIT=0`. Phase 5 Task 5.3 is the canonical
"unconfigured chat captures nothing" test — confirm it is present:
```
python -m pytest bot/tests/ --collect-only -q 2>/dev/null | grep -iE "unconfigured|captures_nothing|gate"
```
Expected: a non-empty list. If empty → REQUIRED-FIX against Phase 5.

**Record into Section 7:** node ids + exit code; explicit confirmation that the unconfigured-chat
test asserts **zero** pushes to `aiwip:botbuf:{chat}` and **zero** enqueues to `aiwip:jobs`.
PASS/FAIL.

**commit:** `docs(qa): record configure-before-capture gate verification in QA gate §7`

---

## Task 7.9 — Section 8: Telethon cutover + single-writer (§6.3, §14 Phase 6)

**Goal:** Decision §16.1 — Telethon is removed **entirely** at the Phase-6 cutover, so the bot is
the sole writer to `Message` (no write race by construction). Verify the old transport and the 6h
scheduler are gone and nothing imports them.

**Step 1 — confirm the Telethon connector and the 6h scheduler are removed:**
```
grep -rniE "telethon|StringSession|TelegramClient|iter_messages|sync_interval_seconds|enqueue_scheduled_syncs" /Users/eduardshatalov/Documents/telegram-task-bot/worker/src /Users/eduardshatalov/Documents/telegram-task-bot/core/src
```
Expected after the cutover: **no matches** in production source (exit 1 from grep). Any live import
of Telethon or the 6h scheduler → REQUIRED-FIX against Phase 6 (the cutover is incomplete).

> NOTE: per the cross-decision note (design §16), Telethon stays live through Phases 1–5 and is
> removed only in Phase 6. This gate runs **after** Phase 6, so the expected state is **removed**.
> If matches remain, record whether Phase 6 actually ran; if it did, this is a blocker.

**Step 2 — confirm the new transport enum value exists** (Decision §16.2,
`ConnectorType.telegram_bot`):
```
grep -nE "telegram_bot" /Users/eduardshatalov/Documents/telegram-task-bot/core/src/aiwip_core/models.py
```
Expected: at least one match (the enum value). Then confirm the Alembic migration that adds the PG
enum value is on head:
```
ALEMBIC_DATABASE_URL="postgresql+psycopg://aiwip:aiwip@localhost:5432/aiwip" python -m alembic -c /Users/eduardshatalov/Documents/telegram-task-bot/core/alembic.ini heads
```
Record the head revision; confirm **exactly one** head (no divergent branches). The two additive
migrations are chained **linearly** in ship order (Phase 1 ships first per design §14):
`2fe660361238 → <phase-1 unresolved_mentions> → c1d2e3f4a5b6 (telegram_bot)` — i.e. Phase 6's
`telegram_bot` migration sets `down_revision = '<phase-1 unresolved_mentions revision id>'`, **not**
`'2fe660361238'`. If `alembic heads` returns **two** heads, both migrations branched from the same
parent (`2fe660361238`) and were never re-chained → REQUIRED-FIX against Phase 6 (re-point its
`down_revision` to the Phase-1 revision so the chain is linear and a single head holds).

**Step 3 — confirm the suite is still green after the removal** (regression from deleting code):
this is already covered by Task 7.2's full-suite run; cross-reference it here, do not re-run.

**Record into Section 8:** the (expected-empty) Telethon grep result, the `telegram_bot` enum
citation, the Alembic head revision. PASS only if Telethon/scheduler are gone AND the enum value
exists AND there is a single migration head.

**commit:** `docs(qa): record Telethon cutover + single-writer verification in QA gate §8`

---

## Task 7.10 — Section 9: BotFather privacy-mode-OFF + bot-admin runbook (§6.3, §13)

**Goal:** §6.3's **operational** requirement: privacy mode **OFF** + bot is a **group admin**,
otherwise capture silently under-collects. The brief requires a **runbook** for this. This task
writes the runbook (operational doc content) into Section 9 — it is the one place this phase
authors procedural content rather than recording a command result.

**Green — write this runbook into Section 9** (verbatim, then mark the consent/data-policy note):

```markdown
### 9. BotFather privacy-mode-OFF + bot-admin runbook

**Why this matters (failure mode):** With Bot API **privacy mode ON** (the BotFather default), a
group bot only receives commands, @mentions, and replies — **not** ordinary chatter. Capture would
silently under-collect and the gate would look green while missing most messages. This is a
**configuration** requirement, not a code one, so it must be verified operationally every time the
bot joins a group.

**One-time BotFather setup (per bot):**
1. DM `@BotFather` → `/mybots` → select the bot → **Bot Settings** → **Group Privacy** →
   **Turn off**. Confirm BotFather replies that privacy mode is **disabled**.
2. Verify via the Bot API (no secret in this doc — read the token from `.env`):
   ```
   curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe" | grep -o '"can_read_all_group_messages":[a-z]*'
   ```
   Expected: `"can_read_all_group_messages":true`. If `false`, privacy mode is still ON — capture
   will under-collect; **block the gate** until corrected.

**Per-group setup (every group the bot captures):**
3. Add the bot to the group.
4. Promote the bot to **admin** (Telegram group → Manage group → Administrators → add the bot).
   A non-admin bot with privacy off still cannot read all messages in some group types.
5. Onboarding consent: the configure-before-capture flow (§7) posts the destination picker; before
   capture begins, the team must accept the **"always-listening" data-policy note** (§13 risk:
   "always-listening bot perceived as surveillance"). Record that the note was shown.

**Operational liveness (so forward-only downtime gaps are detected — §13 accepted risk):**
6. Monitor the bot service per `MONITORING.md` (json-file logs, `docker compose ps` health). The
   bot has **no exposed port** (long-poll), so liveness = container healthy + recent
   `getUpdates` log lines. A downtime gap is **unrecoverable** (no backfill) — alert on the bot
   container restarting or going unhealthy.

**Stale-image reminder (`README.md` gotcha):** after editing `bot/src/...`, rebuild before
trusting any live check: `docker compose build bot && docker compose up -d bot`.

**Checklist (mark each when verified on the real bot):**
- [ ] `getMe` reports `can_read_all_group_messages: true`
- [ ] bot is a group admin in the target group
- [ ] data-policy / consent note shown at onboarding
- [ ] bot container healthy in `docker compose ps`; recent getUpdates log lines present
```

**Verify the runbook section is present and complete:**
```
grep -cE "can_read_all_group_messages|group admin|always-listening|getUpdates" /Users/eduardshatalov/Documents/telegram-task-bot/docs/build/bot-first-capture-qa-gate.md
```
Expected: **≥ 4** (exit 0).

**commit:** `docs(qa): add BotFather privacy + bot-admin runbook to QA gate §9`

---

## Task 7.11 — Section 10: forward-only end-to-end on one real group (§12, §15 MVP)

**Goal:** the brief's "forward-only end-to-end on one real group" — the one **live**, human-driven
acceptance run that proves the whole loop: send a real message → it is captured forward-only →
becomes a Candidate in seconds → the bot DMs a card → a human taps Approve → a WorkItem appears in
the inbox. This is a **manual** checklist (it needs a real Telegram group and a real human tap);
record the observed evidence, not a unit test.

**Step 0 — rebuild every touched service first (the stale-image gotcha is mandatory here):**
```
cd /Users/eduardshatalov/Documents/telegram-task-bot && docker compose build api worker bot && docker compose up -d api worker bot && docker compose ps
```
Record the image build timestamps and confirm all three are **healthy** in `docker compose ps`.
(Per `STAGE-16-verification.md`: a stale image is the #1 cause of a false green here.)

**Step 1 — confirm migrations are applied to the live DB** (the `unresolved_mentions` column and
the `telegram_bot` enum value must exist in the running Postgres, not just in the test DB):
```
docker compose exec postgres psql -U aiwip -d aiwip -c "\d candidates" | grep -i unresolved_mentions
docker compose exec postgres psql -U aiwip -d aiwip -c "SELECT enumlabel FROM pg_enum e JOIN pg_type t ON e.enumtypid=t.oid WHERE t.typname='connectortype';" | grep -i telegram_bot
```
Expected: the `unresolved_mentions` column row, and a `telegram_bot` enum label. If either is
missing → run host-side Alembic upgrade (`README.md` developer-guide command) and re-check; record
that this was needed (it is a known limitation — migrations are not auto-run in-container,
`README.md:160`).

**Step 2 — the live forward-only run (human executor; record each observation):**

| # | Action | Expected observation | Observed | Verdict |
|---|---|---|---|---|
| 1 | Bot is admin + privacy off in a fresh test group (Task 7.10 done) | `getMe.can_read_all_group_messages=true` | | |
| 2 | Configure the chat via the bot (pick a destination) | bot marks chat configured; capture begins | | |
| 3 | Post a real task-shaped message *after* the bot joined | within seconds a `Candidate` row appears (`docker compose exec postgres psql -U aiwip -d aiwip -c "SELECT id,status,created_at FROM candidates ORDER BY id DESC LIMIT 3;"`) | | |
| 4 | A pre-join historical message exists | it is **NOT** captured (forward-only) | | |
| 5 | Bot DMs a card to a **linked admin** | card shows the candidate, with Approve/Reject/Edit/Assign | | |
| 6 | A **non-admin/unlinked** user taps Approve | denied with "ask an admin" (live authz, §6.4) | | |
| 7 | The linked admin taps **Approve** | `POST /approve` fires; a `WorkItem` appears in `inbox` (`SELECT id,status FROM work_items ORDER BY id DESC LIMIT 3;`) | | |
| 8 | The same callback is replayed (re-tap the now-approved card) | no-op (already actioned; 409/handled gracefully) | | |

**Step 3 — confirm seconds-latency** (capture → candidate). Record the timestamp delta between the
message post and the `candidates.created_at`. Expected: **seconds**, not the old 6h window.

**Record into Section 10:** the rebuild timestamps + `docker compose ps` health, the migration
checks, the 8-row live table fully filled, and the latency delta. **The gate cannot PASS without a
successful live forward-only run** (rows 3, 5, 7 are the load-bearing ones; row 6 proves authz; row
4 proves forward-only; row 8 proves replay-safety). Any failed row → REQUIRED-FIX against the
owning phase.

**commit:** `docs(qa): record live forward-only end-to-end run in QA gate §10`

---

## Task 7.12 — Section 11: cookie hardening + secrets posture (§6.4, §13)

**Goal:** §6.4's cookie hardening (`secure=True` on the session cookie) and §13's secrets posture
(bot-admin credential is a top-tier secret; no secret ever in source or this doc).

**Step 1 — confirm `secure=True` on the session cookie** (Phase 2 Task 2.10):
```
grep -nE "set_cookie|secure" /Users/eduardshatalov/Documents/telegram-task-bot/api/src/aiwip_api/routers/auth.py
```
Expected: the `set_cookie(...)` call now includes `secure=True` (today it is
`httponly=True, samesite="lax"` with **no** `secure` at `routers/auth.py:21` — Phase 2 adds it).
If `secure=True` is absent → REQUIRED-FIX against Phase 2.

**Step 2 — confirm no secret is committed anywhere this layer touched** (security-first, §1.6):
```
grep -rniE "TELEGRAM_BOT_TOKEN[[:space:]]*=[[:space:]]*[0-9]|BOT_ADMIN_PASSWORD[[:space:]]*=[[:space:]]*[^[:space:]$]" /Users/eduardshatalov/Documents/telegram-task-bot/bot/src /Users/eduardshatalov/Documents/telegram-task-bot/docker-compose.yml /Users/eduardshatalov/Documents/telegram-task-bot/docs/build/bot-first-capture-qa-gate.md
```
Expected: **no matches** (exit 1) — tokens/passwords live only in `.env` (gitignored). Confirm
`.env.example` documents the keys as **blank placeholders** (Phase 3 Task 3.5):
```
grep -nE "TELEGRAM_BOT_TOKEN=|BOT_ADMIN_PASSWORD=|BOT_ADMIN_EMAIL=" /Users/eduardshatalov/Documents/telegram-task-bot/.env.example
```
Expected: the keys present with empty/placeholder values, never a real token.

**Step 3 — confirm the bot service exposes no port** (long-poll posture, no inbound port — §3, §10):
```
grep -nA15 "^  bot:" /Users/eduardshatalov/Documents/telegram-task-bot/docker-compose.yml | grep -iE "ports|expose"
```
Expected: **no `ports:` mapping** for the `bot` service (a `getUpdates` long-poll bot needs none).
Any published port → record as a finding (NICE-TO-HAVE unless it exposes the API/admin surface, in
which case REQUIRED).

**Record into Section 11:** the `secure=True` citation, the (expected-empty) secret-leak grep, the
`.env.example` placeholders, and the no-port confirmation. PASS/FAIL.

**commit:** `docs(qa): record cookie hardening + secrets posture in QA gate §11`

---

## Task 7.13 — Section 12 + FINAL VERDICT: required-fixes vs nice-to-haves, and the gate decision

**Goal:** close the gate. Consolidate every finding from Sections 1–11 into two lists and write the
binary verdict. **The gate PASSES only with zero unresolved CRITICAL/REQUIRED.**

**Step 1 — build the two lists in Section 12** using this exact table shape:

```markdown
### 12. Required-fixes vs nice-to-haves

**REQUIRED (must be zero unresolved to pass):**

| # | Finding | Section | Owning phase | Severity | Status |
|---|---|---|---|---|---|
| R1 | <e.g. "redeem accepts client telegram_user_id as identity"> | §3 | Phase 2 | CRITICAL | open/fixed |

**NICE-TO-HAVE (do not block the gate):**

| # | Finding | Section | Owning phase | Status |
|---|---|---|---|---|
| N1 | <e.g. "explicit TTL-expiry test deferred as flaky"> | §3 | Phase 2 | deferred |
```

Classify by §3.6 severity: **CRITICAL/REQUIRED** = breaks an Iron Law (human-in-the-loop bypass,
precision violation, auth bypass, secret leak, capture under-collecting, suite red) **or** a
§12-mandatory test is missing. **NICE-TO-HAVE** = polish, optional tests, non-blocking ergonomics.

**Step 2 — compute the verdict.** Count unresolved REQUIRED rows:
- **0 unresolved REQUIRED → `GATE PASSED`.**
- **≥1 unresolved REQUIRED → `GATE FAILED`** — name them in the FINAL VERDICT and route each back to
  its owning phase. Do **not** soften this; per §13 the redeem security review and the assignee
  precision fix are explicitly High-severity gates.

**Step 3 — write the FINAL VERDICT block** at the top of the doc (the placeholder from Task 7.1),
in the `STAGE-16-verification.md` voice — a single blockquote stating PASS/FAIL and the one-line
reason, e.g.:
> **GATE PASSED:** full suite green (exit 0, N passed); /redeem security checklist clean with
> citations; per-callback authz, no-Approve-all, and `<0.60`-never-surfaced all proven; live
> forward-only run captured a message → candidate → approved WorkItem in seconds; zero unresolved
> CRITICAL/REQUIRED.

**Step 4 — write the Summary** (bulleted, mirroring `STAGE-16-verification.md`'s Summary): one line
per section with its PASS/FAIL and the headline number.

**Verify the doc is internally consistent (no empty section, verdict present):**
```
grep -nE "<filled by|<Task 7|<YYYY|<n>|<e\.g\." /Users/eduardshatalov/Documents/telegram-task-bot/docs/build/bot-first-capture-qa-gate.md
```
Expected: **no matches** (every placeholder replaced; exit 1 from grep). Then confirm the verdict
is one of the two allowed strings:
```
grep -cE "GATE PASSED|GATE FAILED" /Users/eduardshatalov/Documents/telegram-task-bot/docs/build/bot-first-capture-qa-gate.md
```
Expected: **≥ 1** (exit 0).

**commit:** `docs(qa): finalize bot-first capture QA gate verdict (§12 + §13)`

---

## SELF-REVIEW checklist

**Spec coverage — every item the brief named for Phase 7 is a task:**
- [x] **Full pytest suite green** → Task 7.2 (exit 0, ≥96 passed, `bot/tests` collected).
- [x] **Dedicated SECURITY re-review of `/redeem`** (single-use, TTL, rate-limit, no
      client-supplied identity, unlinked refusal) → Task 7.4 (named-test rerun + source checklist
      with citations + `/security-review` skill run).
- [x] **Per-callback authz verified** → Task 7.5 (non-admin/unlinked denied; replay no-op; source
      confirms the `from_user.id → User.role==admin` chain + server-side re-fetch).
- [x] **BotFather privacy-mode-OFF + bot-admin runbook** → Task 7.10 (runbook authored into §9,
      incl. `getMe.can_read_all_group_messages` check + admin promotion + consent note).
- [x] **Forward-only end-to-end on one real group** → Task 7.11 (live 8-row run; forward-only,
      seconds-latency, live authz denial, approve→WorkItem, replay-safety).
- [x] **Precision-over-recall + no-Approve-all + `<0.60` never surfaced** → Task 7.7 (named tests +
      adversarial *expected-empty* greps: no `approve.?all` affordance, no auto-approve in
      digest/ingest, `<0.60` structurally unreachable).
- [x] **Required-fixes vs nice-to-haves; zero unresolved CRITICAL/REQUIRED to pass** → Task 7.13
      (two-list classification by §3.6 severity + binary GATE PASSED/FAILED verdict).
- [x] Implements §12 (every §12 test family has a re-run task: assignee bug 7.3, redeem 7.4, authz
      7.5, connector/debounce 7.6, confirmation 7.7, baseline 7.2) and §13 (risk mitigations
      evidenced: redeem security 7.4, assignee precision 7.3, privacy-misconfig runbook 7.10,
      always-listening consent 7.10, Telethon-removal liveness 7.9+7.10, bot-admin secret 7.12,
      stale-image 7.11).

**This phase writes a doc, not product code:**
- [x] The only file created is `docs/build/bot-first-capture-qa-gate.md` (Task 7.1). No file under
      `api/`, `worker/`, `bot/`, `core/` is edited (surgical / one-production-editor — CLAUDE.md
      §1.5, §11.3). Defects route back to the owning phase as required-fixes; this gate re-runs
      after they land.

**Zero placeholders:** no "TBD", "TODO", "add validation", "handle edge cases", "similar to Task
N", "etc.", "and so on" appear in any task. (The angle-bracket tokens like `<n>`, `<filled by…>`
are *intentional fill-in slots inside the produced QA doc*, and Task 7.13's final check asserts they
are all replaced before the gate can pass — they are not plan placeholders.) Every verify step gives
an exact command and expected exit code / output.

**Type / name consistency with the other phases:**
- Endpoint paths exactly match Phase 2 + design §9: `POST /api/auth/telegram-link/start`,
  `POST /api/auth/telegram/redeem`.
- Redis prefixes match the cross-phase contract: `tglink:` / `tglink:rl:tg:` / `tglink:rl:ip:`
  (Phase 2), `aiwip:botbuf:{chat}` / `aiwip:botlock:{chat}` / `aiwip:botcfg:{chat}` (Phases 5/6),
  `botuser:` (per-user prefs) / `botcard:` (per-chat surfaced-watermark) (Phase 4) — distinct from
  the intra-cycle `aiwip:botdigest:{chat}` coalesce buffer — `aiwip:jobs` (core). No new prefix is
  introduced here.
- Test file names referenced match the suite: `worker/tests/test_extract.py`,
  `api/tests/test_telegram_link.py`, `bot/tests/test_authz.py`; `-k` selectors are used wherever a
  precise filename is owned by a not-yet-written phase (Phase 4 has no plan file yet), so the gate
  degrades gracefully to "select by keyword, fail if zero selected".
- `ConnectorType.telegram_bot`, `Candidate.unresolved_mentions`, `CandidateOut` additive fields,
  `secure=True` — all consumed by name exactly as Phases 1/2/6 define them; none redefined.
- The QA doc structure mirrors `docs/build/STAGE-16-verification.md` (FINAL VERDICT → numbered
  evidence → Summary), the established stage-report pattern in this repo.

**Dependency notes (cross-phase):**
- **Runs LAST.** This gate assumes Phases 1–6 have all landed (§14 ordering). Running it earlier
  produces REQUIRED-FIX rows for every absent surface (by design) and a GATE FAILED verdict.
- **Phase 4 has no written plan file** in `docs/specs/impl-plan/` yet (only 1, 2, 3, 5 exist).
  Tasks 7.5/7.6/7.7 therefore target Phase 4's surfaces by spec name (`authz.py`, `cards.py`,
  `handlers.py`, `digest.py`) and by `-k` keyword, and treat "zero tests selected" as a REQUIRED-FIX
  against Phase 4 rather than assuming a filename. When Phase 4's plan lands, swap the `-k`
  selectors for its exact node ids.
- **Live checks need the running Docker stack** and host-side Alembic migrations (`README.md`
  developer guide): `unresolved_mentions` column + `telegram_bot` enum must be applied to the live
  `aiwip` DB, not just the test DB (Task 7.11 Step 1). In-container migrations are a known
  un-wired limitation (`README.md:160`).
- **Resolves two Phase-2 deferrals** (its dependency-notes 1 and 2): the explicit
  `secrets.compare_digest` question and the explicit TTL-expiry test are *decided* in Task 7.4 —
  this gate is the place those were routed to.
- **Two-phase verdict, not idempotent product code.** Re-running the gate after fixes is expected;
  each run overwrites `docs/build/bot-first-capture-qa-gate.md` with fresh evidence and a fresh
  verdict (the date line records which run).
