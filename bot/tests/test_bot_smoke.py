"""Phase 3 — bot package smoke test (host-side, no network). Named test_bot_smoke to avoid a
basename clash with worker/tests/test_smoke.py (pytest prepend import mode, no __init__.py)."""
import aiwip_bot


def test_package_imports_and_has_version():
    assert aiwip_bot.__version__ == "0.1.0"
