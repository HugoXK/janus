from __future__ import annotations

from datetime import datetime, timezone

from janus.data.blob import LocalBlobStore
from janus.memory.models import Observation, ObservationKind
from janus.memory.store import JanusStore


def _observation(obs_id: str, raw_hash: str) -> Observation:
    return Observation(
        id=obs_id,
        entity_id="ACME",
        kind=ObservationKind.news,
        source="rss",
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        value={"title": obs_id},
        raw_hash=raw_hash,
    )


def test_identical_payloads_share_one_blob(tmp_path) -> None:
    store = LocalBlobStore(tmp_path / "blobs")
    first = store.put(b"same")
    second = store.put(b"same")
    assert first == second
    assert store.metrics() == {"blobs": 1, "bytes": 4}
    assert store.verify(first) is True


def test_canonical_json_is_order_independent(tmp_path) -> None:
    store = LocalBlobStore(tmp_path / "blobs")
    first = store.put_json({"b": 2, "a": 1})
    second = store.put_json({"a": 1, "b": 2})
    assert first == second
    assert store.get_json(first) == {"a": 1, "b": 2}


def test_gc_keeps_referenced_blobs(tmp_path) -> None:
    store = LocalBlobStore(tmp_path / "blobs")
    janus = JanusStore(":memory:")
    shared = store.put(b"shared")
    orphan = store.put(b"orphan")
    janus.insert_observation(_observation("one", shared))
    janus.insert_observation(_observation("two", shared))

    result = store.gc(janus)

    assert result.scanned == 2
    assert result.kept == 1
    assert result.deleted == 1
    assert result.bytes_freed == len(b"orphan")
    assert store.path(shared).exists()
    assert not store.path(orphan).exists()

    janus.connection.execute("DELETE FROM observation WHERE id = 'one'")
    janus.connection.commit()
    assert store.gc(janus).kept == 1
    assert store.path(shared).exists()


def test_gc_dry_run_reports_without_deleting(tmp_path) -> None:
    store = LocalBlobStore(tmp_path / "blobs")
    janus = JanusStore(":memory:")
    orphan = store.put(b"orphan")

    result = store.gc(janus, dry_run=True)

    assert result.deleted == 1
    assert store.path(orphan).exists()


def test_verify_detects_tampering(tmp_path) -> None:
    store = LocalBlobStore(tmp_path / "blobs")
    digest = store.put(b"original")
    store.path(digest).write_bytes(b"tampered")
    assert store.verify(digest) is False


def test_delete_returns_bytes_and_missing_is_none(tmp_path) -> None:
    store = LocalBlobStore(tmp_path / "blobs")
    digest = store.put(b"gone")
    assert store.delete(digest) == 4
    assert store.delete(digest) is None
