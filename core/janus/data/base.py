from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from ..memory.models import Observation


class DataSource(ABC):
    """A pluggable market data adapter.

    Adapters must set ``published_at`` to the time the data was publicly
    available, not the time the request was made. That distinction is what
    makes point-in-time queries honest.
    """

    name: str

    @abstractmethod
    def fetch(self, entity_id: str, start: datetime, end: datetime) -> list[Observation]:
        """Fetch observations for an entity over a time range."""

    def health(self) -> dict[str, str]:
        return {"name": self.name, "status": "unconfigured"}
