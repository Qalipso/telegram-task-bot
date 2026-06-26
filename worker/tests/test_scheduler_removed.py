"""Phase 6 cutover — the 6h scheduler is removed (bot is the single writer, Decisions §16.1)."""
import inspect

from aiwip_worker import consumer, main


def test_enqueue_scheduled_syncs_is_gone():
    assert not hasattr(consumer, "enqueue_scheduled_syncs")


def test_main_does_not_reference_scheduled_sync():
    src = inspect.getsource(main.run)
    assert "enqueue_scheduled_syncs" not in src
    assert "sync_interval_seconds" not in src
