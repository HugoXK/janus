from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import pytest

from janus.analysis.feature_store import FeatureStore
from janus.memory.models import Observation, ObservationKind
from janus.memory.snapshot_archive import (
    export_snapshot,
    import_snapshot,
    verify_snapshot,
)
from janus.memory.store import JanusStore


def _seed() -> JanusStore:
    store = JanusStore(":memory:")
    as_of = datetime(2026, 1, 2, tzinfo=timezone.utc)
    for index in range(2):
        store.insert_observation(
            Observation(
                id=f"news-{index}",
                entity_id="ACME",
                kind=ObservationKind.news,
                source="rss",
                published_at=as_of,
                value={"title": f"story {index}"},
                raw_hash=f"hash-{index}",
            )
        )
    store.insert_observation(
        Observation(
            id="future",
            entity_id="ACME",
            kind=ObservationKind.news,
            source="rss",
            published_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
            value={"title": "future"},
            raw_hash="future",
        )
    )
    FeatureStore(store).materialize(
        "ACME",
        as_of,
        {"close": 101.5, "rsi_14": 61.0, "feature_version": "v1"},
        source_hash="source-1",
    )
    # Fixture features are materialized "now"; pin their knowledge time to the
    # fixture date so an as-of freeze in 2026 is allowed to include them.
    store.connection.execute(
        "UPDATE feature_value SET computed_at = ?", (as_of.isoformat(),)
    )
    return store


def test_export_manifest_and_verify(tmp_path) -> None:
    store = _seed()
    as_of = datetime(2026, 1, 3, tzinfo=timezone.utc)
    manifest = export_snapshot(store, tmp_path / "snap", as_of=as_of)

    assert manifest["counts"] == {"observations": 2, "features": 2}
    assert manifest["lineage"]["as_of"].startswith("2026-01-03")
    assert "observations.json" in manifest["files"]
    assert "features.json" in manifest["files"]
    assert verify_snapshot(tmp_path / "snap").ok is True

    observations = json.loads((tmp_path / "snap" / "observations.json").read_text())
    assert {row["id"] for row in observations} == {"news-0", "news-1"}


def test_tampering_is_detected(tmp_path) -> None:
    store = _seed()
    export_snapshot(store, tmp_path / "snap", as_of=datetime(2026, 1, 3, tzinfo=timezone.utc))
    path = tmp_path / "snap" / "observations.json"
    path.write_text(path.read_text() + " ")

    result = verify_snapshot(tmp_path / "snap")
    assert result.ok is False
    assert any("hash mismatch" in error for error in result.errors)
    with pytest.raises(ValueError, match="verification failed"):
        import_snapshot(JanusStore(":memory:"), tmp_path / "snap")


def test_import_round_trips_observations_and_features(tmp_path) -> None:
    source = _seed()
    as_of = datetime(2026, 1, 2, tzinfo=timezone.utc)
    export_snapshot(source, tmp_path / "snap", as_of=as_of)

    target = JanusStore(":memory:")
    counts = import_snapshot(target, tmp_path / "snap")

    assert counts == {"observations": 2, "features": 2}
    assert target.get_observation("news-0") is not None
    assert target.get_observation("future") is None
    assert FeatureStore(target).get("ACME", as_of) == FeatureStore(source).get(
        "ACME", as_of
    )
    original_hash = source.connection.execute(
        "SELECT DISTINCT features_hash FROM feature_value"
    ).fetchone()[0]
    restored_hash = target.connection.execute(
        "SELECT DISTINCT features_hash FROM feature_value"
    ).fetchone()[0]
    assert restored_hash == original_hash


def test_missing_manifest_is_explicit(tmp_path) -> None:
    result = verify_snapshot(tmp_path / "missing")
    assert result.ok is False
    assert result.errors == ("missing manifest.json",)


def test_archive_cli_export_and_verify(tmp_path, monkeypatch) -> None:
    from typer.testing import CliRunner

    from janus.cli import app

    path = tmp_path / "janus.db"
    store = JanusStore(path)
    as_of = datetime(2026, 1, 2, tzinfo=timezone.utc)
    store.insert_observation(
        Observation(
            id="news",
            entity_id="ACME",
            kind=ObservationKind.news,
            source="rss",
            published_at=as_of,
            value={"title": "story"},
            raw_hash="hash",
        )
    )
    monkeypatch.setenv("JANUS_DB", str(path))
    runner = CliRunner()

    exported = runner.invoke(
        app,
        [
            "archive",
            "export",
            "--out",
            str(tmp_path / "snap"),
            "--as-of",
            as_of.isoformat(),
            "--no-parquet",
        ],
    )
    assert exported.exit_code == 0, exported.output

    verified = runner.invoke(
        app, ["archive", "verify", str(tmp_path / "snap"), "--json"]
    )
    assert verified.exit_code == 0, verified.output
    assert json.loads(verified.output)["ok"] is True


def _rewrite_manifest(target, manifest):
    content = {
        key: manifest[key]
        for key in ("archive_version", "as_of", "lineage", "counts", "files")
        if key in manifest
    }
    manifest["snapshot_hash"] = hashlib.sha256(
        json.dumps(
            content, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
    ).hexdigest()
    (target / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_features_computed_after_as_of_are_excluded(tmp_path) -> None:
    store = _seed()
    store.connection.execute(
        """
        INSERT INTO feature_value
        (entity_id, as_of, name, version, value, features_hash, source_hash, computed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ACME",
            "2026-01-02T00:00:00+00:00",
            "leaked",
            "v1",
            json.dumps(1.0),
            "leak-hash",
            "leak-source",
            "2099-01-01T00:00:00+00:00",
        ),
    )
    target = tmp_path / "snap"
    export_snapshot(store, target, as_of=datetime(2026, 1, 3, tzinfo=timezone.utc))
    features = json.loads((target / "features.json").read_text())
    assert all(row["computed_at"] <= "2026-01-03" for row in features)
    assert not any(row["name"] == "leaked" for row in features)


def test_manifest_missing_required_entry_is_rejected(tmp_path) -> None:
    store = _seed()
    target = tmp_path / "snap"
    export_snapshot(store, target, as_of=datetime(2026, 1, 3, tzinfo=timezone.utc))
    manifest = json.loads((target / "manifest.json").read_text())
    manifest["files"].pop("features.json")
    _rewrite_manifest(target, manifest)

    result = verify_snapshot(target)
    assert result.ok is False
    assert any("required entries" in error for error in result.errors)
    with pytest.raises(ValueError, match="manifest missing"):
        import_snapshot(JanusStore(":memory:"), target)


def test_manifest_unknown_or_traversal_entry_is_rejected(tmp_path) -> None:
    store = _seed()
    target = tmp_path / "snap"
    export_snapshot(store, target, as_of=datetime(2026, 1, 3, tzinfo=timezone.utc))
    manifest = json.loads((target / "manifest.json").read_text())
    manifest["files"]["../escape.json"] = {"sha256": "0" * 64, "bytes": 1, "rows": None}
    _rewrite_manifest(target, manifest)

    result = verify_snapshot(target)
    assert result.ok is False
    assert any("unknown manifest entries" in error for error in result.errors)
