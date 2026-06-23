"""Minimal stdlib logging setup shared by api and worker."""
from __future__ import annotations

import logging
import sys

from .config import settings

_configured = False


def setup_logging() -> None:
    """Configure the root logger once. Idempotent."""
    global _configured
    if _configured:
        return
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
