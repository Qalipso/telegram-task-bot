"""Phase 4 — cross-cycle surfaced-watermark in state.py (Redis prefix botcard:). Real Redis."""
import pytest

from aiwip_bot import state
from aiwip_core.redis_client import get_redis


@pytest.fixture(autouse=True)
def _clean_redis():
    r = get_redis()
    for key in r.scan_iter("botcard:*"):
        r.delete(key)
    yield
    for key in r.scan_iter("botcard:*"):
        r.delete(key)


def test_unset_watermark_is_zero():
    assert state.get_surfaced_watermark(chat_id=800) == 0


def test_set_then_get_watermark():
    state.set_surfaced_watermark(chat_id=800, candidate_id=12)
    assert state.get_surfaced_watermark(chat_id=800) == 12


def test_watermark_only_advances():
    state.set_surfaced_watermark(chat_id=800, candidate_id=12)
    state.set_surfaced_watermark(chat_id=800, candidate_id=5)   # lower id must not lower the mark
    assert state.get_surfaced_watermark(chat_id=800) == 12


def test_already_surfaced_at_or_below_watermark():
    state.set_surfaced_watermark(chat_id=800, candidate_id=12)
    assert state.already_surfaced(chat_id=800, candidate_id=12) is True   # at the mark
    assert state.already_surfaced(chat_id=800, candidate_id=8) is True    # below the mark
    assert state.already_surfaced(chat_id=800, candidate_id=13) is False  # above → new


def test_watermark_is_per_chat():
    state.set_surfaced_watermark(chat_id=801, candidate_id=20)
    assert state.get_surfaced_watermark(chat_id=802) == 0
