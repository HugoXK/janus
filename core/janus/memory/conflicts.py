from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Sequence
from uuid import uuid4

from .models import Observation, utcnow
from .store import JanusStore

SOURCE_TIERS: dict[str, float] = {
    "sec_edgar": 1.0,
    "sec": 1.0,
    "fred": 0.95,
    "tiingo": 0.9,
    "yfinance": 0.8,
    "rss": 0.65,
    "gdelt": 0.5,
}
DEFAULT_TIER = 0.5


def source_tier(source: str, tiers: Optional[dict[str, float]] = None) -> float:
    table = {**SOURCE_TIERS, **(tiers or {})}
    text = str(source).split(":")[0].lower()
    return float(table.get(text, DEFAULT_TIER))


def conflict_key(observation: Observation) -> Optional[tuple[str, str, str]]:
    value = observation.value
    fact = value.get("fact") or value.get("metric") or value.get("field")
    if fact is None:
        return None
    return (observation.entity_id, observation.kind.value, str(fact))


def _normalized(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


@dataclass(frozen=True)
class ConflictValue:
    observation_id: str
    source: str
    published_at: datetime
    confidence: float
    tier: float
    value: dict[str, Any]
    normalized: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["published_at"] = self.published_at.isoformat()
        return payload


@dataclass(frozen=True)
class ConflictGroup:
    entity_id: str
    kind: str
    fact_key: str
    values: tuple[ConflictValue, ...]
    selected_id: Optional[str]
    resolution: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "kind": self.kind,
            "fact_key": self.fact_key,
            "values": [value.to_dict() for value in self.values],
            "selected_id": self.selected_id,
            "resolution": self.resolution,
            "reason": self.reason,
        }


def _score(value: ConflictValue, corroboration: int) -> tuple[float, float, int, datetime]:
    return (value.tier, value.confidence, corroboration, value.published_at)


def detect_conflicts(
    observations: Sequence[Observation],
    *,
    tiers: Optional[dict[str, float]] = None,
) -> list[ConflictGroup]:
    """Group observations by explicit fact key and resolve competing values.

    Sources with no ``fact``/``metric``/``field`` key are ignored: two unrelated
    headlines are not a conflict. Both sides of a conflict are always retained.
    """

    grouped: dict[tuple[str, str, str], list[Observation]] = {}
    for observation in observations:
        key = conflict_key(observation)
        if key is None:
            continue
        grouped.setdefault(key, []).append(observation)

    conflicts: list[ConflictGroup] = []
    for (entity_id, kind, fact_key), rows in sorted(grouped.items()):
        values = [
            ConflictValue(
                observation_id=observation.id,
                source=observation.source,
                published_at=observation.published_at,
                confidence=float(observation.confidence),
                tier=source_tier(observation.source, tiers),
                value=observation.value,
                normalized=_normalized(observation.value),
            )
            for observation in rows
        ]
        distinct = {value.normalized for value in values}
        if len(distinct) < 2:
            continue
        corroboration: dict[str, int] = {}
        for value in values:
            corroboration[value.normalized] = corroboration.get(value.normalized, 0) + 1
        ranked = sorted(
            values,
            key=lambda value: _score(value, corroboration[value.normalized]),
            reverse=True,
        )
        top = ranked[0]
        tied = [
            value
            for value in ranked[1:]
            if value.normalized != top.normalized
            and _score(value, corroboration[value.normalized])
            == _score(top, corroboration[top.normalized])
        ]
        if tied:
            selected_id = None
            resolution = "unresolved"
            reason = "top source tier/confidence/recency is tied"
        else:
            selected_id = top.observation_id
            resolution = "resolved"
            reason = (
                f"selected tier={top.tier:.2f} confidence={top.confidence:.2f} "
                f"corroboration={corroboration[top.normalized]} "
                f"published_at={top.published_at.isoformat()}"
            )
        conflicts.append(
            ConflictGroup(
                entity_id=entity_id,
                kind=kind,
                fact_key=fact_key,
                values=tuple(ranked),
                selected_id=selected_id,
                resolution=resolution,
                reason=reason,
            )
        )
    return conflicts


def scan_store(
    store: JanusStore,
    entity_id: str,
    as_of: datetime,
    *,
    tiers: Optional[dict[str, float]] = None,
) -> list[ConflictGroup]:
    observations = store.query_observations_as_of(
        entity_id, as_of, mode="published"
    )
    return detect_conflicts(observations, tiers=tiers)


@dataclass(frozen=True)
class OverrideRecord:
    id: str
    entity_id: str
    kind: str
    fact_key: str
    selected_observation_id: str
    alternatives: tuple[str, ...]
    actor: str
    reason: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class OverrideStore:
    """Append-only JSONL audit for human conflict overrides."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def record(
        self,
        group: ConflictGroup,
        *,
        selected_observation_id: str,
        actor: str,
        reason: str,
    ) -> OverrideRecord:
        known = {value.observation_id for value in group.values}
        if selected_observation_id not in known:
            raise ValueError(
                f"override selected an observation outside the conflict: "
                f"{selected_observation_id}"
            )
        if not actor:
            raise ValueError("an override needs an actor")
        record = OverrideRecord(
            id=uuid4().hex,
            entity_id=group.entity_id,
            kind=group.kind,
            fact_key=group.fact_key,
            selected_observation_id=selected_observation_id,
            alternatives=tuple(
                value.observation_id
                for value in group.values
                if value.observation_id != selected_observation_id
            ),
            actor=actor,
            reason=reason,
            created_at=utcnow().isoformat(),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")
        return record

    def list(self) -> list[OverrideRecord]:
        if not self.path.exists():
            return []
        records = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            payload["alternatives"] = tuple(payload.get("alternatives", ()))
            records.append(OverrideRecord(**payload))
        return records

    def latest(
        self, entity_id: str, kind: str, fact_key: str
    ) -> Optional[OverrideRecord]:
        matches = [
            record
            for record in self.list()
            if (record.entity_id, record.kind, record.fact_key)
            == (entity_id, kind, fact_key)
        ]
        return matches[-1] if matches else None


def apply_override(
    group: ConflictGroup, override: OverrideRecord
) -> ConflictGroup:
    if (
        group.entity_id != override.entity_id
        or group.kind != override.kind
        or group.fact_key != override.fact_key
    ):
        raise ValueError("override does not match this conflict group")
    return ConflictGroup(
        entity_id=group.entity_id,
        kind=group.kind,
        fact_key=group.fact_key,
        values=group.values,
        selected_id=override.selected_observation_id,
        resolution="override",
        reason=f"override by {override.actor}: {override.reason}",
    )
