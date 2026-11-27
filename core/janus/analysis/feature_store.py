from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from ..memory.models import utcnow
from ..memory.store import JanusStore
from .features import features_hash


class FeatureConflict(ValueError):
    """Raised when a historical feature materialization would be rewritten."""


def _normalize_as_of(as_of: datetime) -> str:
    if as_of.tzinfo is None or as_of.tzinfo.utcoffset(as_of) is None:
        raise ValueError("as_of must be timezone-aware")
    return as_of.astimezone(timezone.utc).isoformat()


class FeatureStore:
    """Point-in-time feature materialization.

    A feature row is keyed by ``(entity_id, as_of, name, version)``. Reads return
    the latest materialization at or before the requested time, so a later
    restatement never leaks into an earlier view.
    """

    def __init__(self, store: JanusStore) -> None:
        self.store = store

    def materialize(
        self,
        entity_id: str,
        as_of: datetime,
        features: dict[str, Any],
        *,
        version: str = "v1",
        source_hash: str = "",
        allow_revision: bool = False,
    ) -> str:
        stamp = _normalize_as_of(as_of)
        digest = features_hash(features)
        with self.store.locked():
            existing = self.store.connection.execute(
                """
                SELECT DISTINCT features_hash FROM feature_value
                WHERE entity_id = ? AND as_of = ? AND version = ?
                """,
                (entity_id, stamp, version),
            ).fetchall()
        hashes = {row["features_hash"] for row in existing}
        if hashes and hashes != {digest} and not allow_revision:
            raise FeatureConflict(
                f"features for {entity_id} at {stamp} ({version}) already exist "
                "with a different hash; use a new version or allow_revision=True"
            )

        computed_at = utcnow().isoformat()
        rows = [
            (
                entity_id,
                stamp,
                name,
                version,
                json.dumps(value, sort_keys=True, default=str),
                digest,
                source_hash,
                computed_at,
            )
            for name, value in features.items()
            if name != "feature_version"
        ]
        with self.store.locked():
            with self.store.connection:
                self.store.connection.executemany(
                    """
                    INSERT INTO feature_value
                    (entity_id, as_of, name, version, value, features_hash, source_hash, computed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(entity_id, as_of, name, version) DO UPDATE SET
                        value = excluded.value,
                        features_hash = excluded.features_hash,
                        source_hash = excluded.source_hash,
                        computed_at = excluded.computed_at
                    """,
                    rows,
                )
        return digest

    def snapshot(
        self,
        entity_id: str,
        as_of: datetime,
        *,
        names: Optional[list[str]] = None,
        version: str = "v1",
    ) -> Optional[dict[str, Any]]:
        """Return the latest materialized features and their identity.

        The snapshot includes the materialization time and the stored
        ``features_hash`` so dashboards can cite the exact feature set they
        render instead of recomputing it from a partial read.
        """

        stamp = _normalize_as_of(as_of)
        with self.store.locked():
            latest = self.store.connection.execute(
                """
                SELECT MAX(as_of) FROM feature_value
                WHERE entity_id = ? AND version = ? AND as_of <= ?
                """,
                (entity_id, version, stamp),
            ).fetchone()[0]
            if latest is None:
                return None
            sql = (
                "SELECT name, value, features_hash FROM feature_value "
                "WHERE entity_id = ? AND version = ? AND as_of = ?"
            )
            params: list[object] = [entity_id, version, latest]
            if names:
                placeholders = ",".join("?" for _ in names)
                sql += f" AND name IN ({placeholders})"
                params.extend(names)
            rows = self.store.connection.execute(sql, params).fetchall()
        features = {row["name"]: json.loads(row["value"]) for row in rows}
        digest = rows[0]["features_hash"] if rows else ""
        return {"as_of": latest, "features": features, "features_hash": digest}

    def get(
        self,
        entity_id: str,
        as_of: datetime,
        *,
        names: Optional[list[str]] = None,
        version: str = "v1",
    ) -> dict[str, Any]:
        snapshot = self.snapshot(entity_id, as_of, names=names, version=version)
        return snapshot["features"] if snapshot else {}

    def history(
        self,
        entity_id: str,
        name: str,
        *,
        version: str = "v1",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self.store.locked():
            rows = self.store.connection.execute(
                """
                SELECT as_of, value, features_hash, source_hash, computed_at
                FROM feature_value
                WHERE entity_id = ? AND name = ? AND version = ?
                ORDER BY as_of DESC
                LIMIT ?
                """,
                (entity_id, name, version, limit),
            ).fetchall()
        return [
            {
                "as_of": row["as_of"],
                "value": json.loads(row["value"]),
                "features_hash": row["features_hash"],
                "source_hash": row["source_hash"],
                "computed_at": row["computed_at"],
            }
            for row in rows
        ]
