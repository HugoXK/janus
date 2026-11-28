from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from .models import Observation
from .store import JanusStore


@dataclass(frozen=True)
class RetentionRule:
    """One source/kind retention window. ``*`` matches any value."""

    source: str = "*"
    kind: str = "*"
    max_age_days: int = 365

    def __post_init__(self) -> None:
        if self.max_age_days < 0:
            raise ValueError("max_age_days must be non-negative")

    def matches(self, observation: Observation) -> bool:
        source = str(observation.source)
        source_base = source.split(":")[0]
        source_ok = self.source in {"*", source, source_base}
        kind_ok = self.kind in {"*", observation.kind.value}
        return source_ok and kind_ok

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RetentionPolicy:
    rules: tuple[RetentionRule, ...] = ()
    default_max_age_days: Optional[int] = None

    def __post_init__(self) -> None:
        if self.default_max_age_days is not None and self.default_max_age_days < 0:
            raise ValueError("default_max_age_days must be non-negative")

    def max_age_for(self, observation: Observation) -> Optional[int]:
        for rule in self.rules:
            if rule.matches(observation):
                return rule.max_age_days
        return self.default_max_age_days

    def expiration(self, observation: Observation) -> Optional[datetime]:
        days = self.max_age_for(observation)
        if days is None:
            return None
        return observation.published_at + timedelta(days=days)

    def expired(self, observation: Observation, as_of: datetime) -> bool:
        expiration = self.expiration(observation)
        return expiration is not None and expiration <= as_of

    def to_dict(self) -> dict[str, Any]:
        return {
            "rules": [rule.to_dict() for rule in self.rules],
            "default_max_age_days": self.default_max_age_days,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RetentionPolicy":
        return cls(
            rules=tuple(RetentionRule(**item) for item in payload.get("rules", [])),
            default_max_age_days=payload.get("default_max_age_days"),
        )


@dataclass(frozen=True)
class RetentionResult:
    as_of: str
    scanned: int
    deleted: int
    kept: int
    by_source: dict[str, int]
    deleted_ids: tuple[str, ...]
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RetentionSkip:
    observation_id: str
    entity_id: str
    kind: str
    source: str
    expiration: Optional[str]


def apply_retention(
    store: JanusStore,
    *,
    as_of: datetime,
    policy: RetentionPolicy,
    dry_run: bool = False,
) -> RetentionResult:
    """Delete observations whose policy expiration is at or before ``as_of``."""

    if as_of.tzinfo is None or as_of.tzinfo.utcoffset(as_of) is None:
        raise ValueError("as_of must be timezone-aware")
    rows = store.connection.execute(
        "SELECT id, entity_id, kind, source, published_at FROM observation"
    ).fetchall()
    expired: list[str] = []
    by_source: dict[str, int] = {}
    for row in rows:
        observation = Observation(
            id=row["id"],
            entity_id=row["entity_id"],
            kind=row["kind"],
            source=row["source"],
            published_at=datetime.fromisoformat(row["published_at"]),
            value={},
            raw_hash="",
        )
        if policy.expired(observation, as_of):
            expired.append(observation.id)
            by_source[observation.source] = by_source.get(observation.source, 0) + 1
    if expired and not dry_run:
        placeholders = ",".join("?" for _ in expired)
        with store.connection:
            store.connection.execute(
                f"DELETE FROM observation WHERE id IN ({placeholders})",
                expired,
            )
    return RetentionResult(
        as_of=as_of.isoformat(),
        scanned=len(rows),
        deleted=len(expired),
        kept=len(rows) - len(expired),
        by_source=dict(sorted(by_source.items())),
        deleted_ids=tuple(sorted(expired)),
        dry_run=dry_run,
    )


def redact_value(value: Any, fields: Iterable[str]) -> Any:
    """Return a deep copy with the named keys masked."""

    names = {str(field).lower() for field in fields}
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if str(key).lower() in names:
                result[key] = "***"
            else:
                result[key] = redact_value(item, names)
        return result
    if isinstance(value, list):
        return [redact_value(item, names) for item in value]
    return value


def redact_observation(observation: Observation, fields: Iterable[str]) -> dict[str, Any]:
    """Mask the requested field names at every depth of the exported payload.

    This covers top-level columns (`source`, `raw_hash`, `raw_uri`, `entity_id`,
    ...) as well as nested keys inside `value`; a name that appears nowhere is a
    no-op rather than an error.
    """

    payload = observation.model_dump(mode="json")
    return redact_value(payload, fields)


def export_redacted(
    observations: Sequence[Observation],
    path: Path,
    *,
    fields: Iterable[str],
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        for observation in observations:
            handle.write(
                json.dumps(
                    redact_observation(observation, fields),
                    sort_keys=True,
                    default=str,
                )
                + "\n"
            )
    return target
