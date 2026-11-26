from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .. import __version__
from ..contracts import SCHEMA_VERSION
from .models import Observation
from .store import JanusStore

ARCHIVE_VERSION = "snapshot-v1"


@dataclass(frozen=True)
class SnapshotVerification:
    ok: bool
    errors: tuple[str, ...]
    snapshot_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _as_of_stamp(as_of: datetime) -> str:
    if as_of.tzinfo is None or as_of.tzinfo.utcoffset(as_of) is None:
        raise ValueError("as_of must be timezone-aware")
    return as_of.astimezone(timezone.utc).isoformat()


def _observation_rows(store: JanusStore, as_of: datetime) -> list[dict[str, Any]]:
    entities = [
        str(row["entity_id"])
        for row in store.connection.execute(
            "SELECT DISTINCT entity_id FROM observation ORDER BY entity_id"
        ).fetchall()
    ]
    rows: list[dict[str, Any]] = []
    for entity_id in entities:
        for observation in store.query_observations_as_of(
            entity_id, as_of, mode="published"
        ):
            rows.append(observation.model_dump(mode="json"))
    return sorted(rows, key=lambda item: (item["entity_id"], item["published_at"], item["id"]))


def _feature_rows(store: JanusStore, as_of: datetime) -> list[dict[str, Any]]:
    stamp = as_of.astimezone(timezone.utc).isoformat()
    rows = store.connection.execute(
        """
        SELECT entity_id, as_of, name, version, value, features_hash, source_hash,
               computed_at
        FROM feature_value
        WHERE as_of <= ?
        ORDER BY entity_id, as_of, name, version
        """,
        (stamp,),
    ).fetchall()
    return [
        {
            "entity_id": row["entity_id"],
            "as_of": row["as_of"],
            "name": row["name"],
            "version": row["version"],
            "value": json.loads(row["value"]),
            "features_hash": row["features_hash"],
            "source_hash": row["source_hash"],
            "computed_at": row["computed_at"],
        }
        for row in rows
    ]


def _write_frame(path: Path, rows: Sequence[dict[str, Any]]) -> bool:
    try:
        import pandas as pd
    except ImportError:  # pragma: no cover - optional dependency
        return False
    try:
        pd.DataFrame(list(rows)).to_parquet(path, index=False)
    except (ImportError, ValueError, ModuleNotFoundError):
        return False
    return True


def export_snapshot(
    store: JanusStore,
    out_dir: Path,
    *,
    as_of: datetime,
    parquet: bool = True,
) -> dict[str, Any]:
    """Write a hash-manifested as-of snapshot archive."""

    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    observations = _observation_rows(store, as_of)
    features = _feature_rows(store, as_of)
    _write_json(target / "observations.json", observations)
    _write_json(target / "features.json", features)

    files: dict[str, dict[str, Any]] = {}
    for name, rows in (("observations.json", observations), ("features.json", features)):
        path = target / name
        files[name] = {"sha256": _digest(path), "bytes": path.stat().st_size, "rows": len(rows)}
    if parquet:
        for name, rows in (("observations.parquet", observations), ("features.parquet", features)):
            path = target / name
            if _write_frame(path, rows):
                files[name] = {
                    "sha256": _digest(path),
                    "bytes": path.stat().st_size,
                    "rows": len(rows),
                }

    lineage = {
        "archive_version": ARCHIVE_VERSION,
        "code_version": __version__,
        "schema_version": SCHEMA_VERSION,
        "store": str(store.path),
        "as_of": _as_of_stamp(as_of),
    }
    counts = {"observations": len(observations), "features": len(features)}
    content = {
        "archive_version": ARCHIVE_VERSION,
        "as_of": _as_of_stamp(as_of),
        "lineage": lineage,
        "counts": counts,
        "files": files,
    }
    snapshot_hash = hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    manifest = {**content, "snapshot_hash": snapshot_hash}
    _write_json(target / "manifest.json", manifest)
    return manifest


def verify_snapshot(in_dir: Path) -> SnapshotVerification:
    target = Path(in_dir)
    manifest_path = target / "manifest.json"
    if not manifest_path.exists():
        return SnapshotVerification(False, ("missing manifest.json",), "")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return SnapshotVerification(False, (f"invalid manifest: {exc}",), "")
    errors: list[str] = []
    files = manifest.get("files", {})
    for name, meta in files.items():
        path = target / name
        if not path.exists():
            errors.append(f"missing file: {name}")
            continue
        if _digest(path) != meta.get("sha256"):
            errors.append(f"hash mismatch: {name}")
        if meta.get("rows") is not None:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                if name.endswith(".json"):
                    errors.append(f"invalid json: {name}")
                continue
            if isinstance(payload, list) and len(payload) != meta["rows"]:
                errors.append(f"row count mismatch: {name}")
    content = {
        key: manifest[key]
        for key in ("archive_version", "as_of", "lineage", "counts", "files")
        if key in manifest
    }
    expected = hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    if expected != manifest.get("snapshot_hash"):
        errors.append("snapshot hash mismatch")
    return SnapshotVerification(
        ok=not errors,
        errors=tuple(errors),
        snapshot_hash=str(manifest.get("snapshot_hash", "")),
    )


def import_snapshot(
    store: JanusStore,
    in_dir: Path,
    *,
    verify: bool = True,
) -> dict[str, int]:
    target = Path(in_dir)
    if verify:
        result = verify_snapshot(target)
        if not result.ok:
            raise ValueError("snapshot verification failed: " + "; ".join(result.errors))
    observations = json.loads((target / "observations.json").read_text(encoding="utf-8"))
    features = json.loads((target / "features.json").read_text(encoding="utf-8"))
    for row in observations:
        store.insert_observation(Observation.model_validate(row))
    with store.connection:
        for row in features:
            store.connection.execute(
                """
                INSERT OR REPLACE INTO feature_value
                (entity_id, as_of, name, version, value, features_hash, source_hash, computed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["entity_id"],
                    row["as_of"],
                    row["name"],
                    row["version"],
                    json.dumps(row["value"], sort_keys=True, default=str),
                    row["features_hash"],
                    row["source_hash"],
                    row["computed_at"],
                ),
            )
    return {"observations": len(observations), "features": len(features)}
