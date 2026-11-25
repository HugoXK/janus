from __future__ import annotations

from datetime import datetime, timezone

from janus.data.base import DataSource, DataUnavailable
from janus.data.scheduler import IngestionScheduler
from janus.memory.models import Observation, ObservationKind
from janus.memory.store import JanusStore


class FakeSource(DataSource):
    name = "fake"

    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.calls = 0

    def fetch(self, entity_id: str, start: datetime, end: datetime) -> list[Observation]:
        self.calls += 1
        if self.calls <= self.failures:
            raise DataUnavailable("temporary failure")
        return [
            Observation(
                id=f"fake:{entity_id}",
                entity_id=entity_id,
                kind=ObservationKind.news,
                source=self.name,
                published_at=start,
                value={"title": "ok"},
                raw_hash=f"hash:{entity_id}",
            )
        ]


def _window() -> tuple[datetime, datetime]:
    return (
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 2, tzinfo=timezone.utc),
    )


def test_retry_then_store() -> None:
    store = JanusStore(":memory:")
    source = FakeSource(failures=1)
    start, end = _window()
    result = IngestionScheduler(store, retries=2).run(source, ["ACME"], start, end)

    assert result.fetched == 1
    assert result.stored == 1
    assert result.failed == 0
    assert source.calls == 2
    assert store.get_observation("fake:ACME") is not None


def test_exhausted_retries_create_a_dead_letter_and_replay() -> None:
    store = JanusStore(":memory:")
    start, end = _window()
    result = IngestionScheduler(store, retries=1).run(
        FakeSource(failures=99), ["ACME"], start, end
    )

    assert result.failed == 1
    assert result.dead_letters == 1
    row = store.connection.execute(
        "SELECT entity_id, replayed_at FROM ingestion_dead_letter"
    ).fetchone()
    assert row["entity_id"] == "ACME"
    assert row["replayed_at"] is None

    replay = IngestionScheduler(store).replay(FakeSource(), start, end)
    assert replay.replayed == 1
    assert replay.failed == 0
    row = store.connection.execute(
        "SELECT replayed_at FROM ingestion_dead_letter"
    ).fetchone()
    assert row["replayed_at"] is not None
