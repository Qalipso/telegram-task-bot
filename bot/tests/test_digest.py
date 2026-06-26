"""Phase 4 — digest coalescing + quiet-hours + one-message-per-cycle (§6.2)."""
import datetime as dt

import pytest

from aiwip_bot import digest
from aiwip_core.redis_client import get_redis


@pytest.fixture(autouse=True)
def _clean_redis():
    r = get_redis()
    for pattern in ("aiwip:botdigest:*", "botcard:*"):
        for key in r.scan_iter(pattern):
            r.delete(key)
    yield
    for pattern in ("aiwip:botdigest:*", "botcard:*"):
        for key in r.scan_iter(pattern):
            r.delete(key)


def test_stage_then_drain_returns_unique_ids_in_order():
    digest.stage_candidate(chat_id=900, candidate_id=3)
    digest.stage_candidate(chat_id=900, candidate_id=7)
    digest.stage_candidate(chat_id=900, candidate_id=3)  # duplicate within the cycle
    ids = digest.drain_staged(chat_id=900)
    assert ids == [3, 7]


def test_drain_clears_the_buffer():
    digest.stage_candidate(chat_id=901, candidate_id=1)
    assert digest.drain_staged(chat_id=901) == [1]
    assert digest.drain_staged(chat_id=901) == []   # second drain is empty (coalesced once)


def test_buffers_are_per_chat():
    digest.stage_candidate(chat_id=902, candidate_id=1)
    digest.stage_candidate(chat_id=903, candidate_id=2)
    assert digest.drain_staged(chat_id=902) == [1]
    assert digest.drain_staged(chat_id=903) == [2]


def test_quiet_hours_wraparound_window():
    assert digest.in_quiet_hours(dt.time(23, 0), start=22, end=7) is True
    assert digest.in_quiet_hours(dt.time(3, 0), start=22, end=7) is True
    assert digest.in_quiet_hours(dt.time(12, 0), start=22, end=7) is False


def test_quiet_hours_same_day_window():
    assert digest.in_quiet_hours(dt.time(3, 0), start=1, end=6) is True
    assert digest.in_quiet_hours(dt.time(8, 0), start=1, end=6) is False


def test_quiet_hours_disabled_is_never_quiet():
    assert digest.in_quiet_hours(dt.time(3, 0), start=22, end=7, enabled=False) is False


def _ready(cid):
    return {"id": cid, "candidate_type": "task", "title": f"Task {cid}", "status": "new",
            "missing_fields": [], "assignee_count": 1, "assignee_ambiguous": False,
            "unresolved_mentions": None}


def _needs(cid):
    return {"id": cid, "candidate_type": "task", "title": f"Task {cid}", "status": "needs_review",
            "missing_fields": ["assignee"], "assignee_count": 0, "assignee_ambiguous": False,
            "unresolved_mentions": ["Саша"]}


def test_digest_counts_ready_and_need_input():
    d = digest.build_digest([_ready(1), _ready(2), _needs(3)])
    assert "3 new" in d.text
    assert "2 ready" in d.text
    assert "1 need" in d.text


def test_digest_has_no_approve_all_button():
    d = digest.build_digest([_ready(1), _ready(2)])
    texts = [b.text for row in d.reply_markup.inline_keyboard for b in row]
    assert not any("all" in t.lower() for t in texts)


def test_digest_one_row_per_candidate_routes_to_single_item():
    d = digest.build_digest([_ready(1), _needs(3)])
    datas = [b.callback_data for row in d.reply_markup.inline_keyboard for b in row]
    assert any(data.endswith("1") for data in datas)
    assert any(data.endswith("3") for data in datas)


def test_empty_digest_is_none():
    assert digest.build_digest([]) is None


class _FakeApiForDigest:
    def __init__(self, by_id):
        self._by_id = by_id

    def get_candidate(self, candidate_id: int) -> dict:
        return {"candidate": self._by_id[candidate_id], "assignees": [], "messages": []}


def test_burst_of_n_candidates_produces_exactly_one_digest():
    chat_id = 950
    cands = {i: _ready(i) for i in range(1, 6)}  # 5 candidates in one burst
    for cid in cands:
        digest.stage_candidate(chat_id=chat_id, candidate_id=cid)

    api = _FakeApiForDigest(cands)
    messages = digest.emit_cycle(chat_id=chat_id, api=api)

    assert len(messages) == 1                       # exactly ONE digest, not 5 cards
    assert "5 new" in messages[0].text
    assert digest.emit_cycle(chat_id=chat_id, api=api) == []  # buffer drained
