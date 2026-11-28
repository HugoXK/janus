from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from janus.memory.models import Observation, ObservationKind
from janus.memory.store import JanusStore


def _observation(index: int) -> Observation:
    return Observation(
        id=f"thread-{index}",
        entity_id="ACME",
        kind=ObservationKind.news,
        source="rss",
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        value={"title": f"story {index}"},
        raw_hash=f"hash-{index}",
    )


def test_shared_connection_serializes_concurrent_reads_and_writes(tmp_path) -> None:
    store = JanusStore(tmp_path / "janus.db")

    def worker(index: int) -> str:
        store.insert_observation(_observation(index))
        rows = store.query_observations_as_of(
            "ACME", datetime(2026, 1, 2, tzinfo=timezone.utc)
        )
        return f"{index}:{len(rows) >= 1}"

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(worker, range(32)))

    assert all(result.endswith(":True") for result in results)
    rows = store.query_observations_as_of(
        "ACME", datetime(2026, 1, 2, tzinfo=timezone.utc)
    )
    assert len(rows) == 32


def test_in_memory_store_is_usable_across_threads() -> None:
    store = JanusStore(":memory:")

    def worker(index: int) -> int:
        store.insert_observation(_observation(index))
        return store.schema_version

    with ThreadPoolExecutor(max_workers=4) as pool:
        versions = list(pool.map(worker, range(8)))

    assert versions == [store.schema_version] * 8
    assert len(
        store.query_observations_as_of(
            "ACME", datetime(2026, 1, 2, tzinfo=timezone.utc)
        )
    ) == 8
