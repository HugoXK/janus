from __future__ import annotations

from datetime import datetime

from ..memory.models import Observation
from .base import DataSource


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
