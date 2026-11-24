from __future__ import annotations

from datetime import datetime

from ..memory.models import Observation
from .base import DataSource


class YFinanceSource(DataSource):
    """Unofficial Yahoo Finance access via ``yfinance``.

    No key required. Delayed, unofficial, and occasionally broken. Use as a
    fallback, never as the sole source of truth.
    """

    name = "yfinance"

    def fetch(self, entity_id: str, start: datetime, end: datetime) -> list[Observation]:
        raise NotImplementedError("yfinance adapter lands in M1")


class FREDSource(DataSource):
    """FRED / ALFRED macro series.

    Env: ``FRED_API_KEY``. Use ALFRED vintages when you need true point-in-time
    macro data rather than today's revised series.
    """

    name = "fred"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key

    def fetch(self, entity_id: str, start: datetime, end: datetime) -> list[Observation]:
        raise NotImplementedError("FRED adapter lands in M1")


class GDELTSource(DataSource):
    """GDELT global news events.

    Free and keyless. Noisy. Good for event detection and entity linking, not
    for taking headlines at face value.
    """

    name = "gdelt"

    def fetch(self, entity_id: str, start: datetime, end: datetime) -> list[Observation]:
        raise NotImplementedError("GDELT adapter lands in M1")


class RSSSource(DataSource):
    """Company IR and publisher RSS feeds.

    Free, stable, and underrated. Deduplicate aggressively: syndication is
    common and the same story will appear under multiple URLs.
    """

    name = "rss"

    def __init__(self, feeds: list[str] | None = None) -> None:
        self.feeds = feeds or []

    def fetch(self, entity_id: str, start: datetime, end: datetime) -> list[Observation]:
        raise NotImplementedError("RSS adapter lands in M1")
