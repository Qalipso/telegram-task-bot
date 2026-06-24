"""Stage 12 — evaluation cases + report."""
from aiwip_api import auth
from aiwip_core import models as m


def _admin(client, db):
    db.add(m.User(email="admin@x.io", role=m.UserRole.admin, password_hash=auth.hash_password("pw123456")))
    db.flush()
    client.post("/api/auth/login", json={"email": "admin@x.io", "password": "pw123456"})


def test_create_manual_case_and_report(client, db):
    _admin(client, db)
    r = client.post("/api/evaluation/cases", json={"input_payload": {"text": "x"}, "expected_output": {"type": "task"}, "result": "pass", "prompt_version": "v1"})
    assert r.status_code == 201 and r.json()["result"] == "pass"
    rep = client.get("/api/evaluation/reports").json()
    assert rep["total"] >= 1 and rep["by_result"].get("pass", 0) >= 1 and rep["pass_rate"] is not None


def test_create_from_candidate_carries_expected(client, db):
    _admin(client, db)
    cand = m.Candidate(candidate_type=m.CandidateType.task, title="Do X", priority=m.Priority.high, status=m.CandidateStatus.approved, model_name="gpt-4o-mini", prompt_version="v1")
    db.add(cand)
    db.flush()
    body = client.post("/api/evaluation/cases", json={"candidate_id": cand.id}).json()
    assert body["expected_output"]["type"] == "task" and body["expected_output"]["title"] == "Do X"
    assert body["prompt_version"] == "v1"  # carried from the candidate


def test_pending_excluded_from_rates(client, db):
    _admin(client, db)
    for res in ["pass", "fail", "partial", "pending"]:
        client.post("/api/evaluation/cases", json={"result": res})
    rep = client.get("/api/evaluation/reports").json()
    assert rep["by_result"]["pending"] == 1 and rep["graded"] == 3  # pending not graded
    assert rep["pass_rate"] == round(1 / 3, 4)


def test_eval_admin_only(client, db):
    db.add(m.User(email="ass@x.io", role=m.UserRole.assignee, password_hash=auth.hash_password("pw123456")))
    db.flush()
    client.post("/api/auth/login", json={"email": "ass@x.io", "password": "pw123456"})
    assert client.get("/api/evaluation/cases").status_code == 403


def test_eval_unauthenticated(client):
    assert client.get("/api/evaluation/reports").status_code == 401
