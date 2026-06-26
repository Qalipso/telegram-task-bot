"""Phase 6 cutover — Telethon is gone; only the bot writes (Decisions §16.1)."""
import importlib

import pytest


def test_telegram_connector_module_is_removed():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("aiwip_worker.connectors.telegram")


def test_factory_rejects_legacy_telegram_after_cutover():
    from aiwip_worker import consumer
    with pytest.raises(ValueError):
        consumer.build_connector("telegram")
