# Phase 1 — API & pipeline hardening (assignee bug fix + CandidateOut fields + migration)

> Implements design spec §6.1 (A)–(F) and §6.2 signal fields, plus §8 data-model delta
> (`Candidate.unresolved_mentions`). Contract: `docs/specs/2026-06-26-bot-first-capture-layer-design.md`.
> This phase touches ONLY: `worker/src/aiwip_worker/extract.py`, `worker/src/aiwip_worker/resolver.py`
> (read-only), `api/src/aiwip_api/schemas.py`, `api/src/aiwip_api/routers/candidates.py`,
> `core/src/aiwip_core/models.py`, one new Alembic migration, and tests under
> `worker/tests/` + `api/tests/`. It does NOT create the bot service (Phase 3+) and does NOT
> touch auth/linking (Phase 2).

---

## Orientation for the implementer (you have zero codebase context — read this first)

**Repo root:** `/Users/eduardshatalov/Documents/telegram-task-bot`

**What this system is.** A Telegram → AI → human-approval pipeline. The worker extracts
`Candidate` rows from chat messages (never auto-creating work items). A `Candidate` carries a
`status` (`new` / `needs_review` / …) and per-field confidences. The API lets an admin
list / view / edit / approve / reject candidates. The bot (later phases) will render confirm
cards from the API's `CandidateOut` JSON.

**The bug you are fixing (spec §6.1).** When a single free-text mention ("Саша") matches TWO
active assignees, the current code (`extract._link_assignees`, extract.py:190-200) links **all**
of them and arbitrarily marks the first as primary, and does **not** downgrade `status` from
`new`. So a high-confidence candidate assigned to the wrong person becomes a one-tap Approve.
The fix: on an ambiguous (`len>1`) match, link **none**, flag `"assignee"` missing, and downgrade
`new → needs_review` — mirroring the existing zero-match path (extract.py:157-161).

**Key existing facts you depend on (do NOT re-paste, just rely on them):**
- `worker/src/aiwip_worker/resolver.py:31` — `resolve_assignees(db, mention) -> list[Assignee]`
  returns ALL active assignees whose normalized keys contain the mention. Zero matches → `[]`,
  ambiguous → 2+. **You will not modify resolver.py.**
- `worker/src/aiwip_worker/extract.py:49-54` — `_status_for(item_confidence)` returns
  `CandidateStatus.new` (≥0.90), `CandidateStatus.needs_review` (≥0.60), else `None` (skip).
- `worker/src/aiwip_worker/extract.py:156-161` — the zero-match downgrade block: appends
  `"assignee"` to `missing_fields` and flips `new → needs_review`.
- `worker/src/aiwip_worker/extract.py:134-152` — the `Candidate(...)` constructor call, which
  already sets all five confidences (`task_confidence`, `context_confidence`,
  `assignee_confidence`, `priority_confidence`, `due_date_confidence`).
- `core/src/aiwip_core/models.py:385-419` — the `Candidate` ORM model. It already has
  `missing_fields` (JSONB) and the five confidence columns. You will ADD `unresolved_mentions`.
- `api/src/aiwip_api/schemas.py:72-84` — `CandidateOut`. Today it exposes only `task_confidence`
  + `missing_fields` (no assignee signal at all). You will ADD fields.
- `api/src/aiwip_api/routers/candidates.py:49-58` — `_set_candidate_assignees(db, candidate, ids)`.
  Today it blindly creates `CandidateAssignee` rows for any id. You will ADD validation.

**Test harness (so your commands are exact):**
- Run from the repo root. `pytest.ini` sets `testpaths = core/tests api/tests worker/tests`,
  `python_files = test_*.py`, `addopts = -ra`.
- The root `conftest.py` forces `DATABASE_URL`/`REDIS_URL` to **localhost** and builds the test
  schema with `Base.metadata.create_all(engine)` from the ORM models — so a new ORM column
  appears in the test DB automatically (the Alembic migration is the **production** path and is
  verified separately in Task 1.7). Requires a reachable local Postgres `aiwip_test` and Redis.
- The `db` fixture is a savepoint-isolated `Session`; service/endpoint `commit()`s roll back.
- API tests get a `client` fixture (`api/tests/conftest.py`) — a `TestClient` with `get_db`
  overridden to the test session. Login helper pattern lives in `api/tests/test_candidates.py:6-10`.
- `worker/tests/test_extract.py` provides `FakeLLMClient` usage and the `_output(...)` / `_chat`
  / `_msg` / `_assignee` helpers you will reuse — but each task below shows the FULL test it adds,
  so you do not have to guess.

**Preflight (run once before Task 1.1; confirms the baseline is green):**
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest -q
```
Expected: all tests pass, exit code `0`. If this fails because Postgres/Redis are not running,
start them first:
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && docker compose up -d postgres redis
```
Then re-run the preflight. **Do not start Task 1.1 until the baseline is green.**

**Commit policy.** Each task lists a Conventional-Commit message line. **Commit ONLY when the
user explicitly asks.** If asked, branch first (never commit on `main`/`master` without consent).

---

> **Task ordering (load-bearing — column-before-code).** The `_link_assignees` GREEN fix
> (Task 1.3) writes `candidate.unresolved_mentions`, an attribute that does not exist on the ORM
> model until the column is added. To keep the Red→verify-fail→Green→verify-pass rhythm clean and
> avoid a spurious `AttributeError`, the ORM column is added in **Task 1.2 (before** the code that
> references it), then the GREEN `_link_assignees` fix is **Task 1.3**, then the
> unresolved-mention RED+GREEN pair is **Task 1.4**. The migration / schema / validation tasks
> (1.5–1.10) are unchanged. This dependency is encoded in the task numbering below; do the tasks
> strictly in order.

## Task 1.1 — RED: ambiguous single mention must NOT link any assignee and must downgrade to needs_review

**Goal:** the lead failing test for the §6.1(A) CRITICAL bug. Two active "Саша" assignees + a
"Саша" mention on a 0.95-confidence task ⇒ candidate ends `needs_review`, with NO
`CandidateAssignee` row and `"assignee"` in `missing_fields`. Today the code links both and stays
`new`, so this test FAILS for the right reason.

> This RED test only depends on the existing `_link_assignees`/zero-match behavior; it does NOT
> reference `unresolved_mentions`, so it runs cleanly at this point. (The column it will later
> need for the GREEN path is added in Task 1.2, before the GREEN fix in Task 1.3.)

**File:** `worker/tests/test_extract.py` (append at end of file).

**Add exactly this test:**
```python
def test_ambiguous_mention_links_none_and_needs_review(db):
    """§6.1(A): a single mention matching 2+ active assignees must link NONE, flag the
    'assignee' missing-field, and downgrade new -> needs_review (mirror the zero-match path)."""
    chat = _chat(db, 908)
    _msg(db, chat, 1)
    # Two ACTIVE assignees that both normalize to "саша".
    db.add(m.Assignee(display_name="Саша", telegram_username="sasha1"))
    db.add(m.Assignee(display_name="Александр", telegram_username="sasha2", aliases=["Саша"]))
    db.flush()
    created = extract.extract_candidates(
        db, chat.id, client=FakeLLMClient(_output(item=0.95, assignees=["Саша"], source=[1]))
    )
    assert len(created) == 1
    c = created[0]
    assert db.query(m.CandidateAssignee).filter_by(candidate_id=c.id).count() == 0
    assert "assignee" in (c.missing_fields or [])
    assert c.status == m.CandidateStatus.needs_review
```

**Verify it FAILS for the right reason:**
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && \
python -m pytest worker/tests/test_extract.py::test_ambiguous_mention_links_none_and_needs_review -q
```
Expected: **1 failed**, non-zero exit. The failure is an `AssertionError` on the
`CandidateAssignee ... count() == 0` line (the current code links both ⇒ count is 2) OR on the
`status == needs_review` line (current code keeps `new`). It must NOT be a collection/import error.

**Commit (only if asked):** `test: red — ambiguous assignee mention must not link any (spec §6.1A)`

---

## Task 1.2 — GREEN (model): add `Candidate.unresolved_mentions` nullable JSONB column

**Goal:** add the ORM column that the `_link_assignees` GREEN fix (Task 1.3) and the
unresolved-mention test (Task 1.4) depend on. Nullable JSONB array of strings, matching the
existing `missing_fields` column style on the same model. This lands **before** any code that
references `candidate.unresolved_mentions`, so the GREEN steps run cleanly.

**File:** `core/src/aiwip_core/models.py`.

**Edit:** in the `Candidate` class, immediately AFTER the `missing_fields` line
(`missing_fields: Mapped[list | None] = mapped_column(JSONB)  # D17`, currently models.py:406),
add a new line:
```python
    unresolved_mentions: Mapped[list | None] = mapped_column(JSONB)  # spec §6.1C: raw unmatched/ambiguous mention text
```

> `JSONB` is already imported at models.py:39 (`from sqlalchemy.dialects.postgresql import JSONB`).
> No other import needed.

**Verify the model imports and the column exists (the test DB schema is built from the ORM via
`Base.metadata.create_all`, so the column will appear automatically when Task 1.3/1.4 tests run):**
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && \
python -c "from aiwip_core.models import Candidate; assert hasattr(Candidate, 'unresolved_mentions'); print('ok')"
```
Expected: prints `ok`, exit code `0`.

**Commit (only if asked):** `feat: add Candidate.unresolved_mentions JSONB column (spec §6.1C, §8)`

---

## Task 1.3 — GREEN: fix `_link_assignees` so ambiguous matches link none and signal ambiguity

**Goal:** make Task 1.1 pass with the minimal source change. `_link_assignees` must, per mention:
link the single match when `len==1`; on `len>1` link none and record the ambiguity so the caller
downgrades. We keep the function's existing return contract (`bool` = "did we link anything")
because the caller (extract.py:157) branches on it — but we also need the caller to downgrade on
ambiguity even when *another* mention linked. To keep this surgical and correct, we change
`_link_assignees` to ALSO preserve the unresolved/ambiguous mention strings on the candidate
(needed by Task 1.4 too) and have the caller treat "any unresolved mention" as a downgrade
trigger. The ORM column it writes already exists (added in Task 1.2).

**Files:** `worker/src/aiwip_worker/extract.py` (two edits).

**Edit A — replace the whole `_link_assignees` function (currently extract.py:190-200) with:**
```python
def _link_assignees(db, candidate, c) -> bool:
    """Link resolved assignees for this candidate, precision-first (spec §6.1A).

    Per mention:
      - exactly one active match  -> link it (first linked match is primary);
      - 2+ matches (ambiguous)    -> link NONE for that mention; record the raw text as
                                     unresolved so the candidate is downgraded + surfaced;
      - 0 matches                 -> record the raw text as unresolved.
    Returns True iff at least one assignee was linked.
    """
    seen: set[int] = set()
    unresolved: list[str] = []
    is_primary = True
    for mention in c.assignees:
        matches = resolver.resolve_assignees(db, mention)
        if len(matches) == 1:
            assignee = matches[0]
            if assignee.id not in seen:
                db.add(CandidateAssignee(candidate_id=candidate.id, assignee_id=assignee.id, confidence=c.confidence.assignee, is_primary=is_primary))
                seen.add(assignee.id)
                is_primary = False
        else:
            # ambiguous (len>1) or unknown (len==0): never guess — preserve the raw mention.
            if mention not in unresolved:
                unresolved.append(mention)
    if unresolved:
        existing = list(candidate.unresolved_mentions or [])
        candidate.unresolved_mentions = existing + [u for u in unresolved if u not in existing]
    return bool(seen)
```

**Edit B — update the caller's downgrade block (currently extract.py:156-161) so it also fires when
a mention was unresolved/ambiguous, not only when nothing was linked.** Replace this block:
```python
        resolved = _link_assignees(db, candidate, c)
        if not resolved:
            if "assignee" not in candidate.missing_fields:
                candidate.missing_fields = [*candidate.missing_fields, "assignee"]
            if candidate.status == CandidateStatus.new:
                candidate.status = CandidateStatus.needs_review
```
with:
```python
        resolved = _link_assignees(db, candidate, c)
        # Downgrade when nothing linked OR any mention was ambiguous/unknown (precision-first).
        if not resolved or candidate.unresolved_mentions:
            if "assignee" not in candidate.missing_fields:
                candidate.missing_fields = [*candidate.missing_fields, "assignee"]
            if candidate.status == CandidateStatus.new:
                candidate.status = CandidateStatus.needs_review
```

> NOTE: `candidate.unresolved_mentions` is the column added in **Task 1.2 (already done before this
> task)**, so the attribute exists on the model and the test DB schema (built from the ORM via
> `Base.metadata.create_all`) already has it. No need to jump ahead — Edit A + Edit B here, then
> verify directly.

**Verify Task 1.1's test now PASSES (Task 1.2's ORM column already exists):**
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && \
python -m pytest worker/tests/test_extract.py::test_ambiguous_mention_links_none_and_needs_review -q
```
Expected: **1 passed**, exit code `0`.

**Verify no regression in the existing extract suite:**
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest worker/tests/test_extract.py -q
```
Expected: all pass (including the pre-existing `test_unresolved_assignee_marks_missing_and_needs_review`
and `test_creates_candidate_with_links_and_ai_run`), exit code `0`.

**Commit (only if asked):** `fix: ambiguous assignee mention links none + downgrades (spec §6.1A,C)`

---

## Task 1.4 — Coverage: zero-match mention preserves the raw mention text on the candidate

**Goal:** lock in §6.1(C) — the unknown ("ghost") mention text is persisted in
`Candidate.unresolved_mentions` so a later `[Assign…]` picker can say *who* was unmatched. Today
the raw mention lives only in `ai_runs.output_payload`.

> **Why this is a coverage test, not a RED test.** Per the column-before-code ordering, the ORM
> column landed in Task 1.2 and the `_link_assignees` fix that writes it landed in Task 1.3, so by
> the time you add this test both of its dependencies already exist and the test PASSES on first
> run. It exists to pin the zero-match (`len==0`) branch of `_link_assignees` distinctly from the
> ambiguous (`len>1`) branch covered by Task 1.1 — preventing a future regression that handles one
> branch but not the other. (The RED proof for this code path is Task 1.1; this test guards a
> second branch through the same fix.)

**File:** `worker/tests/test_extract.py` (append at end).

**Add exactly this test:**
```python
def test_unresolved_mention_text_preserved_on_candidate(db):
    """§6.1(C): the raw unmatched mention is stored on Candidate.unresolved_mentions."""
    chat = _chat(db, 909)
    _msg(db, chat, 1)
    created = extract.extract_candidates(
        db, chat.id, client=FakeLLMClient(_output(item=0.95, assignees=["Сашка"], source=[1]))
    )
    c = created[0]
    assert c.unresolved_mentions == ["Сашка"]
    assert "assignee" in (c.missing_fields or [])
    assert c.status == m.CandidateStatus.needs_review
```

**Verify it PASSES (its dependencies — the column from Task 1.2 and the fix from Task 1.3 — are
already in place; the test DB schema is built from the ORM via `Base.metadata.create_all`, so the
column is present automatically):**
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && \
python -m pytest worker/tests/test_extract.py::test_unresolved_mention_text_preserved_on_candidate -q
```
Expected: **1 passed**, exit code `0`.

**Verify the whole extract suite is still green (Task 1.1's ambiguous path plus this zero-match
path):**
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest worker/tests/test_extract.py -q
```
Expected: all pass, exit code `0`.

**Commit (only if asked):** `test: cover unresolved mention text preserved on candidate (spec §6.1C)`

---

## Task 1.5 — Alembic migration: add `candidates.unresolved_mentions` on head `2fe660361238`

**Goal:** the PRODUCTION DDL for Task 1.2's column. Additive, nullable, matching the migration
style of `core/alembic/versions/2fe660361238_add_users_password_hash.py` and the JSONB style of
the initial schema (`postgresql.JSONB(astext_type=sa.Text())`).

**Step A — generate the revision file with the correct down_revision wired to the current head:**
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot/core && \
ALEMBIC_DATABASE_URL="postgresql+psycopg://aiwip:aiwip@localhost:5432/aiwip" \
python -m alembic revision -m "add candidates.unresolved_mentions"
```
This creates a new file under `core/alembic/versions/` with `down_revision = '2fe660361238'`
(Alembic resolves the current head automatically). Note the generated `revision` id and filename
from the command output.

**Step B — replace the generated file's body** so it reads exactly like this (keep the
auto-generated `revision`/`Create Date` values that Alembic wrote; only the docstring header id
and the function bodies below are authored):
```python
"""add candidates.unresolved_mentions

Revision ID: <KEEP THE GENERATED revision id>
Revises: 2fe660361238
Create Date: <KEEP THE GENERATED timestamp>
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '<KEEP THE GENERATED revision id>'
down_revision: Union[str, None] = '2fe660361238'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'candidates',
        sa.Column('unresolved_mentions', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('candidates', 'unresolved_mentions')
```

> Do NOT change `revision` or `Create Date` from what Alembic generated — only set
> `down_revision = '2fe660361238'` (Alembic already wrote this) and author the two function
> bodies + the `postgresql` import.

**Verify the migration applies cleanly against the dev DB (round-trip up→down→up):**
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot/core && \
ALEMBIC_DATABASE_URL="postgresql+psycopg://aiwip:aiwip@localhost:5432/aiwip" python -m alembic upgrade head && \
ALEMBIC_DATABASE_URL="postgresql+psycopg://aiwip:aiwip@localhost:5432/aiwip" python -m alembic downgrade -1 && \
ALEMBIC_DATABASE_URL="postgresql+psycopg://aiwip:aiwip@localhost:5432/aiwip" python -m alembic upgrade head
```
Expected: each command exits `0`; the upgrade logs `Running upgrade 2fe660361238 -> <new id>,
add candidates.unresolved_mentions`, the downgrade logs the reverse, and the final upgrade
re-applies cleanly.

**Verify there is exactly one head (no branch was introduced):**
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot/core && \
ALEMBIC_DATABASE_URL="postgresql+psycopg://aiwip:aiwip@localhost:5432/aiwip" python -m alembic heads
```
Expected: a single head line ending `(head)` — the new revision id. NOT two heads.

**Commit (only if asked):** `feat: alembic migration for candidates.unresolved_mentions (spec §8)`

---

## Task 1.6 — RED: `CandidateOut` exposes the assignee signal + 4 per-field confidences

**Goal:** prove §6.1(B) + §6.2 — the API response a bot reads must carry `assignee_count`,
`assignee_ambiguous`, `unresolved_mentions`, and the four per-field confidences
(`assignee_confidence`, `priority_confidence`, `due_date_confidence`, `context_confidence`).
Today `CandidateOut` has none of these, so the bot literally cannot detect ambiguity.

**File:** `api/tests/test_candidates.py` (append at end).

**Add exactly this test:**
```python
def test_candidate_out_exposes_assignee_signal_and_confidences(client, db):
    """§6.1B + §6.2: the detail/list payload carries the bot's branching signals."""
    _login(client, db, m.UserRole.admin)
    chat = m.Chat(connector_type=m.ConnectorType.telegram, external_chat_id=950)
    db.add(chat)
    db.flush()
    cand = m.Candidate(
        candidate_type=m.CandidateType.task, title="Do Y", summary="s",
        status=m.CandidateStatus.needs_review, task_confidence=0.95,
        context_confidence=0.8, assignee_confidence=0.7, priority_confidence=0.6,
        due_date_confidence=0.5, missing_fields=["assignee"], unresolved_mentions=["Сашка"],
    )
    db.add(cand)
    db.flush()
    a1 = m.Assignee(display_name="Саша", telegram_username="sasha1")
    a2 = m.Assignee(display_name="Александр", telegram_username="sasha2")
    db.add(a1)
    db.add(a2)
    db.flush()
    db.add(m.CandidateAssignee(candidate_id=cand.id, assignee_id=a1.id, is_primary=True))
    db.add(m.CandidateAssignee(candidate_id=cand.id, assignee_id=a2.id, is_primary=False))
    db.flush()

    out = client.get(f"/api/candidates/{cand.id}").json()["candidate"]
    assert out["assignee_count"] == 2
    assert out["assignee_ambiguous"] is True  # 2+ linked OR unresolved mentions present
    assert out["unresolved_mentions"] == ["Сашка"]
    assert out["assignee_confidence"] == 0.7
    assert out["priority_confidence"] == 0.6
    assert out["due_date_confidence"] == 0.5
    assert out["context_confidence"] == 0.8
```

**Verify it FAILS for the right reason:**
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && \
python -m pytest "api/tests/test_candidates.py::test_candidate_out_exposes_assignee_signal_and_confidences" -q
```
Expected: **1 failed**, non-zero exit. The failure is a `KeyError`/`AssertionError` because the
`out` dict has no `assignee_count` / `assignee_ambiguous` / per-field confidence keys yet. It must
NOT be a collection or 401/403 auth error (the login helper handles auth).

**Commit (only if asked):** `test: red — CandidateOut assignee signal + per-field confidences (spec §6.1B,§6.2)`

---

## Task 1.7 — GREEN: add the new fields to `CandidateOut`

**Goal:** make Task 1.6 pass. Add the four DB-backed per-field confidences (they map straight
from the ORM via `from_attributes`), plus `unresolved_mentions` (DB-backed), plus the two
**derived** fields `assignee_count` and `assignee_ambiguous`. The derived fields are NOT on the
ORM model, so they must be computed when serializing.

The detail endpoint (`get_candidate`, candidates.py:73-111) returns
`CandidateOut.model_validate(candidate).model_dump()`. To compute `assignee_count` /
`assignee_ambiguous` from the candidate's linked `CandidateAssignee` rows, we add them as
Pydantic computed fields backed by the ORM relationship `candidate.candidate_assignees`
(declared at models.py:417). `from_attributes=True` lets a computed field read the ORM object.

**File:** `api/src/aiwip_api/schemas.py`.

**Edit A — update the import at the top of the file** so `computed_field` is available.
Replace this line (schemas.py:6):
```python
from pydantic import BaseModel, ConfigDict
```
with:
```python
from pydantic import BaseModel, ConfigDict, computed_field
```

**Edit B — replace the entire `CandidateOut` class (currently schemas.py:72-84) with:**
```python
class CandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    candidate_type: CandidateType
    title: str | None = None
    summary: str | None = None
    priority: Priority | None = None
    due_date: dt.datetime | None = None
    status: CandidateStatus
    task_confidence: float | None = None
    # §6.2 per-field confidences (give the bot a richer policy than status alone).
    assignee_confidence: float | None = None
    priority_confidence: float | None = None
    due_date_confidence: float | None = None
    context_confidence: float | None = None
    missing_fields: list[str] | None = None
    # §6.1C: raw unmatched/ambiguous mention text, for the [Assign…] picker title.
    unresolved_mentions: list[str] | None = None
    created_at: dt.datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def assignee_count(self) -> int:
        """Number of linked assignees (CandidateAssignee rows)."""
        return len(getattr(self, "_candidate_assignees", []) or [])

    @computed_field  # type: ignore[prop-decorator]
    @property
    def assignee_ambiguous(self) -> bool:
        """§6.1B: ambiguous if 2+ assignees are linked OR any mention went unresolved."""
        return self.assignee_count > 1 or bool(self.unresolved_mentions)
```

> PROBLEM: a `computed_field` property cannot read the ORM `candidate_assignees` relationship
> directly off `self`, because `from_attributes` copies declared fields only — the relationship
> is not a declared `CandidateOut` field, so `self` has no `candidate_assignees`. To make the
> count available without adding a heavy nested schema, declare a private attribute that DOES get
> populated from the ORM. Replace the `assignee_count` property body's `getattr(...)` approach by
> adding a real declared field that maps the relationship to its length. The clean, minimal way:
> add a hidden list field aliased to the ORM relationship and count it.

**Edit B (corrected, use THIS version of the class instead of the one above):**
```python
class CandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    candidate_type: CandidateType
    title: str | None = None
    summary: str | None = None
    priority: Priority | None = None
    due_date: dt.datetime | None = None
    status: CandidateStatus
    task_confidence: float | None = None
    # §6.2 per-field confidences (give the bot a richer policy than status alone).
    assignee_confidence: float | None = None
    priority_confidence: float | None = None
    due_date_confidence: float | None = None
    context_confidence: float | None = None
    missing_fields: list[str] | None = None
    # §6.1C: raw unmatched/ambiguous mention text, for the [Assign…] picker title.
    unresolved_mentions: list[str] | None = None
    created_at: dt.datetime

    # Populated from the ORM relationship Candidate.candidate_assignees; excluded from output.
    # We only use its length to derive assignee_count, so map it to a list of ids.
    candidate_assignees: list[int] = Field(default_factory=list, exclude=True)

    @field_validator("candidate_assignees", mode="before")
    @classmethod
    def _coerce_assignee_rows(cls, v: object) -> list[int]:
        """Accept the ORM list of CandidateAssignee rows (or anything iterable) and reduce it
        to a list of assignee ids, so model_validate(orm_candidate) populates it."""
        if not v:
            return []
        ids: list[int] = []
        for row in v:
            aid = getattr(row, "assignee_id", None)
            if aid is not None:
                ids.append(aid)
        return ids

    @computed_field  # type: ignore[prop-decorator]
    @property
    def assignee_count(self) -> int:
        return len(self.candidate_assignees)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def assignee_ambiguous(self) -> bool:
        """§6.1B: ambiguous if 2+ assignees are linked OR any mention went unresolved."""
        return self.assignee_count > 1 or bool(self.unresolved_mentions)
```

**Edit A (corrected) — the class above also needs `Field` and `field_validator`.** Replace the
import line (schemas.py:6) with:
```python
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator
```

> `candidate_assignees` is declared with `exclude=True` so it never appears in the serialized
> JSON — only the derived `assignee_count` does. `from_attributes=True` makes
> `CandidateOut.model_validate(candidate)` read the ORM `candidate.candidate_assignees`
> relationship into this field, and the validator reduces those rows to ids before counting.

**Verify Task 1.6's test now PASSES:**
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && \
python -m pytest "api/tests/test_candidates.py::test_candidate_out_exposes_assignee_signal_and_confidences" -q
```
Expected: **1 passed**, exit code `0`.

**Verify the existing candidate API tests still pass (list/detail/edit/approve/reject use
`CandidateOut`):**
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest api/tests/test_candidates.py -q
```
Expected: all pass, exit code `0`. (In particular `test_list_and_detail` exercises both the list
`response_model=list[CandidateOut]` and the detail `model_dump()` path with the relationship
loaded.)

**Commit (only if asked):** `feat: CandidateOut exposes assignee signal + per-field confidences (spec §6.1B,§6.2)`

---

## Task 1.8 — RED: `_set_candidate_assignees` rejects unknown / inactive assignee ids (422)

**Goal:** prove §6.1(D) — a PATCH with `assignee_ids` that don't exist, or point at an
`is_active=False` assignee, must return **422** and must NOT create a dangling
`CandidateAssignee`. Today `_set_candidate_assignees` (candidates.py:49-58) blindly inserts any id.

**File:** `api/tests/test_candidates.py` (append at end).

**Add exactly these two tests:**
```python
def test_patch_rejects_nonexistent_assignee_id(client, db):
    """§6.1D: a stale/forged assignee id must be rejected (422), not silently linked."""
    _login(client, db, m.UserRole.admin)
    cand = _seed_candidate(db)  # has one valid assignee (Bob)
    missing_id = 999999
    r = client.patch(f"/api/candidates/{cand.id}", json={"assignee_ids": [missing_id]})
    assert r.status_code == 422, r.text
    # The original assignment is unchanged (transaction not committed on rejection).
    detail = client.get(f"/api/candidates/{cand.id}").json()
    assert detail["candidate"]["assignee_count"] == 1


def test_patch_rejects_inactive_assignee_id(client, db):
    """§6.1D: an inactive assignee must not be assignable via the bot/admin PATCH."""
    _login(client, db, m.UserRole.admin)
    cand = _seed_candidate(db)
    ghost = m.Assignee(display_name="Ghost", telegram_username="ghost", is_active=False)
    db.add(ghost)
    db.flush()
    r = client.patch(f"/api/candidates/{cand.id}", json={"assignee_ids": [ghost.id]})
    assert r.status_code == 422, r.text
```

**Verify they FAIL for the right reason:**
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && \
python -m pytest "api/tests/test_candidates.py::test_patch_rejects_nonexistent_assignee_id" \
"api/tests/test_candidates.py::test_patch_rejects_inactive_assignee_id" -q
```
Expected: **2 failed**, non-zero exit. The current code returns `200` (it links the bad id), so
the `status_code == 422` assertions fail. (The nonexistent-id case may instead surface a DB
`IntegrityError` 500 due to the FK; either way it is NOT 422, so the test fails as intended and
the fix in Task 1.9 makes it a clean 422 *before* any insert.)

**Commit (only if asked):** `test: red — reject unknown/inactive assignee ids on PATCH (spec §6.1D)`

---

## Task 1.9 — GREEN: validate `assignee_ids` in `_set_candidate_assignees`

**Goal:** make Task 1.8 pass. Before deleting/recreating links, look up every requested id among
**active** assignees; if any id is missing or inactive, raise `HTTPException(422)` BEFORE any
mutation, so the request is rejected atomically.

**File:** `api/src/aiwip_api/routers/candidates.py` (two edits).

**Edit A — ensure `Assignee` is imported (it already is at candidates.py:18-27, in the
`from aiwip_core.models import (...)` block). No import change is needed.** Confirm
`HTTPException` and `status` are imported (they are, at candidates.py:10). No import change needed.

**Edit B — replace the `_set_candidate_assignees` function (currently candidates.py:49-58) with:**
```python
def _set_candidate_assignees(db: Session, candidate: Candidate, assignee_ids: list[int]) -> None:
    """Replace the candidate's responsible person(s) (first id = primary) and keep the
    'assignee' missing-field flag in sync. Validates that every id is an ACTIVE assignee
    (spec §6.1D): a stale/forged/inactive id is rejected with 422 before any mutation."""
    if assignee_ids:
        active_ids = set(
            db.execute(
                select(Assignee.id).where(
                    Assignee.id.in_(assignee_ids), Assignee.is_active.is_(True)
                )
            ).scalars().all()
        )
        invalid = [aid for aid in assignee_ids if aid not in active_ids]
        if invalid:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Unknown or inactive assignee id(s): {invalid}",
            )
    db.query(CandidateAssignee).filter_by(candidate_id=candidate.id).delete()
    for i, aid in enumerate(assignee_ids):
        db.add(CandidateAssignee(candidate_id=candidate.id, assignee_id=aid, is_primary=(i == 0)))
    missing = [f for f in (candidate.missing_fields or []) if f != "assignee"]
    if not assignee_ids:
        missing.append("assignee")
    candidate.missing_fields = missing
```

> `select` is already imported at candidates.py:11 (`from sqlalchemy import desc, select`).
> Raising before the `delete()` guarantees the rejected request leaves the existing assignment
> untouched (the test asserts `assignee_count == 1` afterward).

**Verify Task 1.8's tests now PASS:**
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && \
python -m pytest "api/tests/test_candidates.py::test_patch_rejects_nonexistent_assignee_id" \
"api/tests/test_candidates.py::test_patch_rejects_inactive_assignee_id" -q
```
Expected: **2 passed**, exit code `0`.

**Verify the existing edit test (valid assignee path) still passes:**
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && \
python -m pytest "api/tests/test_candidates.py::test_edit_assigns_responsible_and_syncs_missing_fields" -q
```
Expected: **1 passed**, exit code `0`.

**Commit (only if asked):** `feat: validate assignee_ids (reject unknown/inactive) on candidate PATCH (spec §6.1D)`

---

## Task 1.10 — Full-suite verification gate (Iron Law §3.5: fresh evidence)

**Goal:** prove the whole repo suite is green after all Phase-1 changes — no regression in core,
worker, or api tests, and the new tests included.

**Run the full suite fresh:**
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot && python -m pytest -q
```
Expected: **all tests pass**, exit code `0`. The total count should be the prior baseline
(~94–96) PLUS the 5 new tests added in this phase
(`test_ambiguous_mention_links_none_and_needs_review`,
`test_unresolved_mention_text_preserved_on_candidate`,
`test_candidate_out_exposes_assignee_signal_and_confidences`,
`test_patch_rejects_nonexistent_assignee_id`, `test_patch_rejects_inactive_assignee_id`).

**Confirm the Alembic chain is single-headed and current (production-path check):**
```bash
cd /Users/eduardshatalov/Documents/telegram-task-bot/core && \
ALEMBIC_DATABASE_URL="postgresql+psycopg://aiwip:aiwip@localhost:5432/aiwip" python -m alembic heads
```
Expected: exactly one head (the `unresolved_mentions` revision), exit code `0`.

**Commit (only if asked):** `chore: phase-1 verification — full suite green + single alembic head`

---

## SELF-REVIEW CHECKLIST

**Spec coverage (§6.1, §6.2, §8):**
- [x] §6.1(A) ambiguous (`len>1`) match links NONE + downgrades `new → needs_review` — Tasks 1.1, 1.2.
- [x] §6.1(B) `CandidateOut` gains `assignee_count`, `assignee_ambiguous`, `unresolved_mentions` — Tasks 1.6, 1.7.
- [x] §6.2 four per-field confidences (`assignee/priority/due_date/context`) added to `CandidateOut` — Tasks 1.6, 1.7.
- [x] §6.1(C) `Candidate.unresolved_mentions` nullable JSONB column + written in `extract._link_assignees` + Alembic migration on head `2fe660361238` — Tasks 1.2, 1.3, 1.4, 1.5.
- [x] §6.1(D) `_set_candidate_assignees` rejects unknown/inactive ids with 422 — Tasks 1.8, 1.9.
- [x] Lead RED test is the two-"Саша" ambiguity case ending `needs_review` with no primary — Task 1.1 (first task).
- [ ] §6.1(E) alias-capture button and §6.1(F) `telegram_user_id` pre-resolution are explicitly OUT of Phase 1 (spec §14 assigns capture/UX to Phases 3–6; §15 lists alias-capture as a fast-follow). Not implemented here by design.

**Zero placeholders:** No "TBD"/"TODO"/"add validation"/"handle edge cases"/"etc."/"similar to
Task N". Every code block is complete and copy-pasteable; every verify step has an exact command +
expected exit code. (Task 1.7 deliberately shows a first-attempt class then the corrected class,
with an explicit instruction to use the corrected version — this is guidance, not a placeholder.)

**Type / name consistency with other phases:**
- Column name `Candidate.unresolved_mentions` (JSONB list[str], nullable) matches the spec §8 row
  and is the same name reused by the `CandidateOut.unresolved_mentions` field — Phase 4 (bot
  `cards.py`) reads `unresolved_mentions`, `assignee_count`, `assignee_ambiguous` from this exact
  JSON shape.
- `CandidateOut` field names: `assignee_count: int`, `assignee_ambiguous: bool`,
  `unresolved_mentions: list[str] | None`, `assignee_confidence/priority_confidence/`
  `due_date_confidence/context_confidence: float | None` — these are the bot-facing contract for
  Phase 4 confirm cards (§6.2 band routing).
- HTTP status for invalid assignee ids is **422** (`HTTP_422_UNPROCESSABLE_ENTITY`) — Phase 4's
  bot `api_client` must map 422 on the assign action as "stale button / invalid pick" per §10
  ("409/404/422 conversationally").
- `_link_assignees` keeps its `-> bool` return contract; the caller now also downgrades on
  `candidate.unresolved_mentions` being non-empty.

**Dependency notes (ordering is load-bearing):**
- Task 1.2's source edit references `candidate.unresolved_mentions`, which does not exist until
  Task 1.4 adds the ORM column. **Do Task 1.4 before re-verifying Task 1.1/1.2.** The plan flags
  this inline in Task 1.2.
- Tasks 1.3/1.6 RED steps are run BEFORE their respective GREEN columns/fields exist, to confirm
  they fail for the right reason; then 1.4 (model) / 1.7 (schema) make them pass.
- The Alembic migration (Task 1.5) is the production DDL only; the test suite does NOT run
  migrations (conftest uses `Base.metadata.create_all`), so 1.5 is verified independently against
  the dev DB and via `alembic heads`.
- No change to `resolver.py` (read-only dependency), `promotion.py`, `auth.py`, or any bot file.
- Out of scope here and owned by later phases: `ConnectorType` enum value `telegram_bot`
  (Phase 6), the redeem/link endpoints (Phase 2), all bot service files (Phases 3–5).
