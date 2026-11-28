from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from janus.analysis.feature_store import FeatureStore
from janus.memory.store import JanusStore


def test_feature_store_reads_and_writes_are_thread_safe(tmp_path) -> None:
    store = JanusStore(tmp_path / "janus.db")
    features = FeatureStore(store)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def writer(index: int) -> str:
        as_of = start + timedelta(days=index)
        return features.materialize(
            "ACME", as_of, {"close": 100.0 + index, "feature_version": "v1"}
        )

    def reader(index: int) -> dict:
        as_of = start + timedelta(days=index % 16)
        return features.get("ACME", as_of)

    with ThreadPoolExecutor(max_workers=8) as pool:
        writes = list(pool.map(writer, range(16)))
        reads = list(pool.map(reader, range(64)))

    assert len([value for value in writes if value]) == 16
    assert all(isinstance(value, dict) for value in reads)
    latest = features.get("ACME", start + timedelta(days=15))
    assert latest["close"] == 115.0
