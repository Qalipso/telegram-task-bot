"""AI extraction pipeline: context window → LLM → validated Candidates (never WorkItems).

Logs every call to ai_runs (D23 input_hash). Invalid/odd output is logged and skipped — it never
crashes the pipeline (llm-extraction-spec "Error Handling"). Confidence bands (item):
>=0.90 strong (status=new), 0.70–0.90 needs_review, <0.70 skipped.
"""
from __future__ import annotations

import datetime as dt
import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from aiwip_core import audit
from aiwip_core.logging import get_logger
from aiwip_core.models import (
    AiRun,
    AiRunType,
    Assignee,
    AuditAction,
    AuditEntityType,
    Candidate,
    CandidateAssignee,
    CandidateMessage,
    CandidateMessageRole,
    CandidateStatus,
    CandidateType,
    Message,
    Priority,
)

from . import context as context_mod
from . import resolver
from .llm import prompts
from .llm import schema as llm_schema
from .llm.client import OpenAIClient

logger = get_logger("aiwip.worker.extract")

ACTIVE_TYPES = {"task", "request", "reminder", "idea", "knowledge"}
PRIORITIES = {"critical", "high", "medium", "low"}


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _status_for(item_confidence: float) -> CandidateStatus | None:
    if item_confidence >= 0.90:
        return CandidateStatus.new
    if item_confidence >= 0.70:
        return CandidateStatus.needs_review
    return None  # too weak — skip


def _parse_due(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
    except (ValueError, TypeError):
        return None


def extract_candidates(
    db: Session,
    chat_id: int,
    client=None,
    window: int = context_mod.DEFAULT_WINDOW,
    topic_gap_minutes: int = context_mod.DEFAULT_TOPIC_GAP_MINUTES,
) -> list[Candidate]:
    client = client or OpenAIClient()
    ctx = context_mod.build_context(db, chat_id, window=window, topic_gap_minutes=topic_gap_minutes)
    if not ctx.messages:
        return []

    assignees = db.execute(select(Assignee).where(Assignee.is_active.is_(True))).scalars().all()
    system, user = prompts.build_messages(ctx, assignees, _now())
    input_hash = hashlib.sha256(f"{prompts.PROMPT_VERSION}\n{system}\n{user}".encode()).hexdigest()

    result = client.extract(system, user, prompts.JSON_SCHEMA)
    ai_run = AiRun(
        run_type=AiRunType.extraction,
        model_provider="openai",
        model_name=result.model,
        prompt_version=prompts.PROMPT_VERSION,
        input_hash=input_hash,
        input_payload={"system": system, "user": user},
        output_payload=result.output,
        tokens_input=result.tokens_input,
        tokens_output=result.tokens_output,
        cost=result.cost,
        status=result.status,
        error_message=result.error,
    )
    db.add(ai_run)

    if result.status != "success" or result.output is None:
        db.commit()
        logger.warning("extraction not usable (status=%s) chat=%s", result.status, chat_id)
        return []

    try:
        parsed = llm_schema.LLMOutput.model_validate(result.output)
    except Exception as exc:  # noqa: BLE001
        ai_run.status = "invalid_schema"
        ai_run.error_message = str(exc)
        db.commit()
        logger.warning("extraction schema invalid chat=%s: %s", chat_id, exc)
        return []

    # Map external message ids (referenced by the LLM + the window) to internal ids.
    ext_ids = {cm.external_message_id for cm in ctx.messages}
    for c in parsed.candidates:
        ext_ids.update(c.source_message_ids)
        ext_ids.update(c.supporting_message_ids)
    rows = db.execute(
        select(Message).where(Message.chat_id == chat_id, Message.external_message_id.in_(ext_ids))
    ).scalars().all()
    ext_to_id = {m.external_message_id: m.id for m in rows}

    created: list[Candidate] = []
    for c in parsed.candidates:
        if c.type not in ACTIVE_TYPES:
            continue
        status = _status_for(c.confidence.item)
        if status is None:
            continue

        candidate = Candidate(
            candidate_type=CandidateType(c.type),
            title=c.title or None,
            summary=c.summary or None,
            priority=Priority(c.priority) if c.priority in PRIORITIES else None,
            due_date=_parse_due(c.due_date),
            status=status,
            task_confidence=c.confidence.item,
            context_confidence=c.confidence.context,
            assignee_confidence=c.confidence.assignee,
            priority_confidence=c.confidence.priority,
            due_date_confidence=c.confidence.due_date,
            reasoning_summary=c.reasoning_summary or None,
            missing_fields=list(c.missing_fields),
            context_summary=parsed.context_summary or ctx.summary,
            model_name=result.model,
            prompt_version=prompts.PROMPT_VERSION,
        )
        db.add(candidate)
        db.flush()

        _link_messages(db, candidate, c, ctx, ext_to_id)
        resolved = _link_assignees(db, candidate, c)
        if not resolved:
            if "assignee" not in candidate.missing_fields:
                candidate.missing_fields = [*candidate.missing_fields, "assignee"]
            if candidate.status == CandidateStatus.new:
                candidate.status = CandidateStatus.needs_review
        audit.record_audit(db, None, AuditAction.candidate_created, AuditEntityType.candidate, candidate.id)
        created.append(candidate)

    db.commit()
    logger.info("extraction chat=%s created %s candidate(s)", chat_id, len(created))
    return created


def _link_messages(db, candidate, c, ctx, ext_to_id) -> None:
    linked: set[int] = set()
    for ext in c.source_message_ids:
        if ext in ext_to_id and ext not in linked:
            db.add(CandidateMessage(candidate_id=candidate.id, message_id=ext_to_id[ext], role=CandidateMessageRole.primary))
            linked.add(ext)
    for ext in c.supporting_message_ids:
        if ext in ext_to_id and ext not in linked:
            db.add(CandidateMessage(candidate_id=candidate.id, message_id=ext_to_id[ext], role=CandidateMessageRole.supporting))
            linked.add(ext)
    for cm in ctx.messages:
        ext = cm.external_message_id
        if ext in ext_to_id and ext not in linked:
            db.add(CandidateMessage(candidate_id=candidate.id, message_id=ext_to_id[ext], role=CandidateMessageRole.context))
            linked.add(ext)


def _link_assignees(db, candidate, c) -> bool:
    seen: set[int] = set()
    is_primary = True
    for mention in c.assignees:
        for assignee in resolver.resolve_assignees(db, mention):
            if assignee.id in seen:
                continue
            db.add(CandidateAssignee(candidate_id=candidate.id, assignee_id=assignee.id, confidence=c.confidence.assignee, is_primary=is_primary))
            seen.add(assignee.id)
            is_primary = False
    return bool(seen)
