"""Evaluation foundation (admin-only): build eval cases (incl. from reviewed candidates) + report.

A human-reviewed candidate IS ground truth, so a case can be seeded from one (expected_output =
the candidate's fields). The report gives basic metrics (pass/fail/partial rates, by prompt_version),
excluding `pending` from rates (evaluation-plan.md).
"""
from __future__ import annotations

from collections import Counter, defaultdict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from aiwip_api import auth
from aiwip_api.schemas import CreateEvaluationCaseRequest, EvaluationCaseOut
from aiwip_core.models import Candidate, CandidateAssignee, CandidateMessage, EvaluationCase, User

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])


def _expected_from_candidate(db: Session, candidate: Candidate) -> tuple[list[int], dict]:
    source_ids = [
        cm.message_id
        for cm in db.execute(select(CandidateMessage).where(CandidateMessage.candidate_id == candidate.id)).scalars()
    ]
    assignee_ids = [
        ca.assignee_id
        for ca in db.execute(select(CandidateAssignee).where(CandidateAssignee.candidate_id == candidate.id)).scalars()
    ]
    expected = {
        "type": candidate.candidate_type.value,
        "title": candidate.title,
        "summary": candidate.summary,
        "priority": candidate.priority.value if candidate.priority else None,
        "due_date": candidate.due_date.isoformat() if candidate.due_date else None,
        "assignee_ids": assignee_ids,
    }
    return source_ids, expected


@router.post("/cases", response_model=EvaluationCaseOut, status_code=status.HTTP_201_CREATED)
def create_case(
    payload: CreateEvaluationCaseRequest,
    _admin: User = Depends(auth.require_admin),
    db: Session = Depends(auth.get_db),
) -> EvaluationCase:
    source_ids = payload.source_message_ids
    expected = payload.expected_output
    model_name = payload.model_name
    prompt_version = payload.prompt_version

    if payload.candidate_id is not None:
        candidate = db.get(Candidate, payload.candidate_id)
        if candidate is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Candidate not found")
        derived_ids, derived_expected = _expected_from_candidate(db, candidate)
        source_ids = source_ids or derived_ids
        expected = expected or derived_expected
        model_name = model_name or candidate.model_name
        prompt_version = prompt_version or candidate.prompt_version

    case = EvaluationCase(
        source_message_ids=source_ids,
        input_payload=payload.input_payload,
        expected_output=expected,
        actual_output=payload.actual_output,
        result=payload.result,
        score=payload.score,
        comments=payload.comments,
        model_name=model_name,
        prompt_version=prompt_version,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


@router.get("/cases", response_model=list[EvaluationCaseOut])
def list_cases(_admin: User = Depends(auth.require_admin), db: Session = Depends(auth.get_db)):
    return db.execute(select(EvaluationCase).order_by(EvaluationCase.id)).scalars().all()


@router.get("/reports")
def report(_admin: User = Depends(auth.require_admin), db: Session = Depends(auth.get_db)) -> dict:
    cases = db.execute(select(EvaluationCase)).scalars().all()
    by_result = Counter(c.result.value for c in cases)
    graded = sum(by_result[r] for r in ("pass", "fail", "partial"))
    by_prompt: dict[str, Counter] = defaultdict(Counter)
    for c in cases:
        by_prompt[c.prompt_version or "unknown"][c.result.value] += 1
    return {
        "total": len(cases),
        "by_result": dict(by_result),
        "graded": graded,
        "pass_rate": round(by_result["pass"] / graded, 4) if graded else None,
        "partial_rate": round(by_result["partial"] / graded, 4) if graded else None,
        "fail_rate": round(by_result["fail"] / graded, 4) if graded else None,
        "by_prompt_version": {k: dict(v) for k, v in by_prompt.items()},
    }
