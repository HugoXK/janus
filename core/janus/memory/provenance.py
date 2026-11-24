from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .models import Observation
from .store import JanusStore


@dataclass(frozen=True)
class Provenance:
    observation: Observation

    @property
    def citation(self) -> str:
        obs = self.observation
        where = obs.raw_uri or obs.raw_hash
        return f"{obs.source} {obs.published_at.isoformat()} {where}"


class ProvenanceTracer:
    """Resolve a claim or observation to its source record."""

    def __init__(self, store: JanusStore) -> None:
        self.store = store

    def trace(self, observation_id: str) -> Optional[Provenance]:
        observation = self.store.get_observation(observation_id)
        return Provenance(observation) if observation else None

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
