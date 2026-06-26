"""Telegram Bot API service for the AI Work Intelligence Platform.

Bot-first capture & confirm layer (design spec §10). This package owns the
getUpdates long-poll loop and the confirm-loop UX; it never writes to the
database directly — all writes go through the existing API over httpx.
"""

__version__ = "0.1.0"
