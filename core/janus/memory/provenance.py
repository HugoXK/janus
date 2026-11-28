from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from .models import Observation
from .store import JanusStore


class ProvenanceError(KeyError):
    """Raised when a citation cannot resolve to a known observation."""


@dataclass(frozen=True)
class Provenance:
    observation: Observation

    @property
    def citation(self) -> str:
        obs = self.observation
        where = obs.raw_uri or obs.raw_hash
        return f"{obs.source} {obs.published_at.isoformat()} {where}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation": self.observation.model_dump(mode="json"),
            "citation": self.citation,
        }


class ProvenanceTracer:
    """Resolve a claim or observation to its source record."""

    def __init__(self, store: JanusStore) -> None:
        self.store = store

    def trace(self, observation_id: str) -> Optional[Provenance]:
        observation = self.store.get_observation(observation_id)
        return Provenance(observation) if observation else None

    def require(self, observation_id: str) -> Provenance:
        traced = self.trace(observation_id)
        if traced is None:
            raise ProvenanceError(f"observation not found: {observation_id}")
        return traced

    def catalog(self, limit: int = 200) -> list[Provenance]:
        if limit < 0:
            raise ValueError("limit must be >= 0")
        rows = self.store.connection.execute(
            "SELECT * FROM observation ORDER BY published_at DESC, id LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            Provenance(self.store._row_to_observation(row))
            for row in rows
        ]

    def search(
        self,
        entity_id: str,
        text: str,
        as_of: datetime,
        limit: int = 20,
    ) -> list[Provenance]:
        observations = self.store.search_observations(
            entity_id=entity_id,
            text=text,
            as_of=as_of,
            limit=limit,
        )
        return [Provenance(observation) for observation in observations]
