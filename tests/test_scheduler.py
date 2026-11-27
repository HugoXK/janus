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


# --- #73: per-source concurrency limit -------------------------------------
#
# Red-before-green contract for issue #73 (scope comment 7153408519, Lead pins).
# Synchronisation is events only: no sleeps, no wall-clock assertions. A hard
# timeout is a failure guard, never part of a pass condition.
#
# Store connections are created and used on the thread that calls run(), because
# JanusStore opens sqlite with the default check_same_thread=True. Every test
# therefore performs its store reads inside the worker thread and hands back
# plain data.

import threading  # noqa: E402

import pytest  # noqa: E402

_TIMEOUT = 10.0


class GatedSource(DataSource):
    """Block inside fetch until released, recording the peak number in flight."""

    def __init__(self, name: str, *, target: int) -> None:
        self.name = name
        self.target = target
        self.lock = threading.Lock()
        self.in_flight = 0
        self.max_in_flight = 0
        self.started: list[str] = []
        self.reached = threading.Event()
        self.release = threading.Event()
        self.aborted = False

    def fetch(
        self, entity_id: str, start: datetime, end: datetime
    ) -> list[Observation]:
        with self.lock:
            self.in_flight += 1
            self.started.append(entity_id)
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            if self.in_flight >= self.target:
                self.reached.set()
            aborted = self.aborted
        if not aborted and not self.release.wait(_TIMEOUT):
            with self.lock:
                self.aborted = True
            raise DataUnavailable("gated source was never released")
        with self.lock:
            self.in_flight -= 1
        return [
            Observation(
                id=f"{self.name}:{entity_id}",
                entity_id=entity_id,
                kind=ObservationKind.news,
                source=self.name,
                published_at=start,
                value={"title": "ok"},
                raw_hash=f"hash:{entity_id}",
            )
        ]


class FirstCallGatedSource(DataSource):
    """Block only the first fetch, so a second entity's start is observable."""

    name = "gated-one"

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.started: list[str] = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self._blocked_once = False

    def fetch(
        self, entity_id: str, start: datetime, end: datetime
    ) -> list[Observation]:
        with self.lock:
            self.started.append(entity_id)
            block = not self._blocked_once
            self._blocked_once = True
        if block:
            self.entered.set()
            assert self.release.wait(_TIMEOUT), "first fetch was never released"
        return [
            Observation(
                id=f"{self.name}:{entity_id}",
                entity_id=entity_id,
                kind=ObservationKind.news,
                source=self.name,
                published_at=start,
                value={"title": "ok"},
                raw_hash=f"hash:{entity_id}",
            )
        ]


def _snapshot(store: JanusStore) -> dict[str, object]:
    """Plain-data view of a run's persisted state; must run on the store thread."""

    observations = [
        (row["id"], row["entity_id"])
        for row in store.connection.execute(
            "SELECT id, entity_id FROM observation ORDER BY rowid"
        ).fetchall()
    ]
    dead_letters = [
        (row["entity_id"], row["error"], row["replayed_at"])
        for row in store.connection.execute(
            "SELECT entity_id, error, replayed_at FROM ingestion_dead_letter ORDER BY id"
        ).fetchall()
    ]
    runs = [
        (row["status"], row["counts"], row["finished_at"])
        for row in store.connection.execute(
            "SELECT status, counts, finished_at FROM ingestion_run ORDER BY rowid"
        ).fetchall()
    ]
    return {"observations": observations, "dead_letters": dead_letters, "runs": runs}


def test_max_concurrency_below_one_raises_value_error() -> None:
    """AC2: reject impossible limits with the exact message, before touching the store."""

    store = JanusStore(":memory:")
    for bad in (0, -1):
        with pytest.raises(ValueError) as excinfo:
            IngestionScheduler(store, max_concurrency=bad)
        assert str(excinfo.value) == f"max_concurrency must be >= 1, got {bad}"

    created = store.connection.execute("SELECT COUNT(*) FROM ingestion_run").fetchone()[0]
    assert created == 0


def test_default_and_explicit_one_produce_identical_results() -> None:
    """AC1: the default must be byte-for-byte the existing sequential behaviour."""

    start, end = _window()
    entities = ["ACME", "BETA"]

    def one_run(**kwargs: int) -> dict[str, object]:
        store = JanusStore(":memory:")
        result = IngestionScheduler(store, **kwargs).run(FakeSource(), entities, start, end)
        snapshot = _snapshot(store)
        snapshot["result"] = (
            result.source,
            result.fetched,
            result.stored,
            result.failed,
            result.dead_letters,
        )
        return snapshot

    default = one_run()
    explicit = one_run(max_concurrency=1)

    assert default["observations"] == explicit["observations"]
    assert default["dead_letters"] == explicit["dead_letters"]
    assert default["result"] == explicit["result"]
    # finished_at is wall-clock, so it differs by construction between two runs.
    # AC1 pins status and counts; require both runs finished, not equal timestamps.
    assert [run[:2] for run in default["runs"]] == [run[:2] for run in explicit["runs"]]
    assert default["runs"][0][2] and explicit["runs"][0][2]
    assert default["observations"] == [
        ("fake:ACME", "ACME"),
        ("fake:BETA", "BETA"),
    ]


def test_max_concurrency_three_never_exceeds_the_cap() -> None:
    """AC3: peak in-flight is exactly 3, a fourth fetch never starts, all 8 store."""

    start, end = _window()
    entities = [f"E{index}" for index in range(8)]
    source = GatedSource("gated", target=3)
    box: dict[str, object] = {}

    def worker() -> None:
        try:
            store = JanusStore(":memory:")
            result = IngestionScheduler(store, max_concurrency=3).run(
                source, entities, start, end
            )
            box["result"] = (result.stored, result.failed, result.dead_letters)
            box["snapshot"] = _snapshot(store)
        except BaseException as exc:  # surface the real failure, not a gate timeout
            box["error"] = exc
            source.reached.set()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    try:
        assert source.reached.wait(_TIMEOUT), "three fetches never overlapped"
        if "error" in box:
            raise box["error"]  # type: ignore[misc]
        with source.lock:
            assert source.in_flight == 3
    finally:
        source.release.set()
        thread.join(_TIMEOUT)

    assert not thread.is_alive(), "the run never finished"
    assert source.max_in_flight == 3, "a fourth fetch started above the cap"
    assert box["result"] == (8, 0, 0)
    observations = box["snapshot"]["observations"]  # type: ignore[index]
    assert [entity for _, entity in observations] == entities


def test_max_concurrency_one_never_overlaps_two_entities() -> None:
    """AC4: at limit 1, entity B does not start while A is inside fetch."""

    start, end = _window()
    source = FirstCallGatedSource()
    box: dict[str, object] = {}

    def worker() -> None:
        try:
            store = JanusStore(":memory:")
            result = IngestionScheduler(store, max_concurrency=1).run(
                source, ["A", "B"], start, end
            )
            box["result"] = (result.stored, result.failed)
        except BaseException as exc:
            box["error"] = exc
            source.entered.set()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    try:
        assert source.entered.wait(_TIMEOUT), "the first fetch never started"
        if "error" in box:
            raise box["error"]  # type: ignore[misc]
        with source.lock:
            assert source.started == ["A"], "a second entity ran while the first was in fetch"
    finally:
        source.release.set()
        thread.join(_TIMEOUT)

    assert not thread.is_alive(), "the run never finished"
    assert source.started == ["A", "B"]
    assert box["result"] == (2, 0)


def test_two_schedulers_reach_their_caps_independently() -> None:
    """AC5: the limit is per run, not a process-global semaphore."""

    start, end = _window()
    first = GatedSource("first", target=2)
    second = GatedSource("second", target=2)
    threads = []

    def worker(source: GatedSource) -> None:
        try:
            store = JanusStore(":memory:")
            IngestionScheduler(store, max_concurrency=2).run(
                source, ["X", "Y"], start, end
            )
        except BaseException as exc:
            box[source.name] = exc
            source.reached.set()

    box: dict[str, BaseException] = {}
    for source in (first, second):
        thread = threading.Thread(target=worker, args=(source,), daemon=True)
        thread.start()
        threads.append(thread)

    try:
        assert first.reached.wait(_TIMEOUT), "the first run never reached its cap"
        if "first" in box:
            raise box["first"]
        assert second.reached.wait(_TIMEOUT), "the second run was blocked by the first"
        if "second" in box:
            raise box["second"]
    finally:
        first.release.set()
        second.release.set()
        for thread in threads:
            thread.join(_TIMEOUT)

    for source in (first, second):
        assert source.max_in_flight == 2


# --- #73: single writer, run row, per-entity retries (AC6-AC9) --------------
#
# These extend the same contract without changing the five tests above. Store
# reads happen on the thread that calls run(), because JanusStore opens sqlite
# with check_same_thread=True.

import json  # noqa: E402
import sqlite3  # noqa: E402
from collections.abc import Callable  # noqa: E402


class RecordingConnection:
    """Record the thread that issues every statement, then delegate."""

    def __init__(
        self, connection: sqlite3.Connection, record: Callable[[], None]
    ) -> None:
        self._connection = connection
        self._record = record

    def execute(
        self, sql: str, parameters: tuple[object, ...] = ()
    ) -> sqlite3.Cursor:
        self._record()
        return self._connection.execute(sql, parameters)

    def commit(self) -> None:
        self._record()
        self._connection.commit()


class RecordingStore(JanusStore):
    """A store that remembers which threads touched it."""

    def __init__(self) -> None:
        self.store_threads: set[int] = set()
        self.store_calls = 0
        super().__init__(":memory:")
        self._recording = RecordingConnection(self._conn, self._record)

    def _record(self) -> None:
        self.store_threads.add(threading.get_ident())
        self.store_calls += 1

    @property
    def connection(self) -> RecordingConnection:  # type: ignore[override]
        return self._recording

    def insert_observation(self, observation: Observation) -> None:
        self._record()
        super().insert_observation(observation)


class LaterEntityFinishesFirstSource(DataSource):
    """A returns only after B has finished, so completion order is B then A."""

    name = "later-first"

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.threads: set[int] = set()
        self.a_entered = threading.Event()
        self.b_finished = threading.Event()

    def fetch(
        self, entity_id: str, start: datetime, end: datetime
    ) -> list[Observation]:
        with self.lock:
            self.threads.add(threading.get_ident())
        if entity_id == "A":
            self.a_entered.set()
            if not self.b_finished.wait(_TIMEOUT):
                raise DataUnavailable("B never finished first")
        else:
            if not self.a_entered.wait(_TIMEOUT):
                raise DataUnavailable("A never started")
            self.b_finished.set()
        return [
            Observation(
                id=f"{self.name}:{entity_id}",
                entity_id=entity_id,
                kind=ObservationKind.news,
                source=self.name,
                published_at=start,
                value={"title": "ok"},
                raw_hash=f"hash:{entity_id}",
            )
        ]


class EntityFailingSource(DataSource):
    """Stores every entity except the named ones, which always raise."""

    name = "entity-failing"

    def __init__(self, failing: set[str]) -> None:
        self.failing = set(failing)
        self.lock = threading.Lock()
        self.calls: dict[str, int] = {}

    def fetch(
        self, entity_id: str, start: datetime, end: datetime
    ) -> list[Observation]:
        with self.lock:
            self.calls[entity_id] = self.calls.get(entity_id, 0) + 1
        if entity_id in self.failing:
            raise DataUnavailable("provider timeout")
        return [
            Observation(
                id=f"{self.name}:{entity_id}",
                entity_id=entity_id,
                kind=ObservationKind.news,
                source=self.name,
                published_at=start,
                value={"title": "ok"},
                raw_hash=f"hash:{entity_id}",
            )
        ]


class ExplodingSource(DataSource):
    """Fails entity B with a plain RuntimeError, not a retryable DataUnavailable."""

    name = "exploding"

    def fetch(
        self, entity_id: str, start: datetime, end: datetime
    ) -> list[Observation]:
        if entity_id == "B":
            raise RuntimeError("worker blew up")
        return [
            Observation(
                id=f"{self.name}:{entity_id}",
                entity_id=entity_id,
                kind=ObservationKind.news,
                source=self.name,
                published_at=start,
                value={"title": "ok"},
                raw_hash=f"hash:{entity_id}",
            )
        ]


class FailOnceWithPeerSource(DataSource):
    """RETRY fails its first attempt but only after PEER has finished.

    Holding the failing attempt open while another entity completes widens the
    window in which two attempts for the same entity could overlap, so the
    per-entity in-flight counter can actually observe such a bug.
    """

    name = "fail-once"

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.calls: dict[str, int] = {}
        self.in_flight: dict[str, int] = {}
        self.max_in_flight: dict[str, int] = {}
        self.peer_finished = threading.Event()

    def fetch(
        self, entity_id: str, start: datetime, end: datetime
    ) -> list[Observation]:
        with self.lock:
            self.calls[entity_id] = self.calls.get(entity_id, 0) + 1
            attempt = self.calls[entity_id]
            self.in_flight[entity_id] = self.in_flight.get(entity_id, 0) + 1
            self.max_in_flight[entity_id] = max(
                self.max_in_flight.get(entity_id, 0), self.in_flight[entity_id]
            )
        try:
            if entity_id == "RETRY":
                if attempt == 1:
                    if not self.peer_finished.wait(_TIMEOUT):
                        raise DataUnavailable("PEER never finished")
                    raise DataUnavailable("first attempt fails")
            else:
                self.peer_finished.set()
            return [
                Observation(
                    id=f"{self.name}:{entity_id}",
                    entity_id=entity_id,
                    kind=ObservationKind.news,
                    source=self.name,
                    published_at=start,
                    value={"title": "ok"},
                    raw_hash=f"hash:{entity_id}",
                )
            ]
        finally:
            with self.lock:
                self.in_flight[entity_id] -= 1


def test_store_writes_stay_on_the_run_thread_in_input_order() -> None:
    """AC6: pooled fetches, single-writer persistence in input entity order."""

    start, end = _window()
    source = LaterEntityFinishesFirstSource()
    box: dict[str, object] = {}

    def worker() -> None:
        try:
            # sqlite3 refuses cross-thread use, so the store is born here too.
            store = RecordingStore()
            ident = threading.get_ident()
            result = IngestionScheduler(store, retries=0, max_concurrency=2).run(
                source, ["A", "B"], start, end
            )
            box["ident"] = ident
            box["store_threads"] = set(store.store_threads)
            box["counts"] = (result.fetched, result.stored, result.failed)
            box["rows"] = [
                (row["id"], row["entity_id"])
                for row in store.connection.execute(
                    "SELECT id, entity_id FROM observation ORDER BY rowid"
                ).fetchall()
            ]
        except BaseException as exc:  # surface the real failure, not a timeout
            box["error"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(_TIMEOUT)

    assert not thread.is_alive(), "the run never finished"
    if "error" in box:
        raise box["error"]  # type: ignore[misc]

    assert box["counts"] == (2, 2, 0)
    assert box["rows"] == [("later-first:A", "A"), ("later-first:B", "B")], (
        "distinct entities on one thread must persist in input order, "
        "not completion order (B finished first)"
    )
    assert box["ident"] != threading.get_ident(), "run() must not be the test thread"
    assert box["store_threads"] == {box["ident"]}, (
        "every store call must happen on the thread that called run()"
    )
    assert box["ident"] not in source.threads, "fetches must run in the pool"


def test_pooled_failures_dead_letter_in_input_order() -> None:
    """AC7: two failing entities dead-letter in input order at either limit."""

    start, end = _window()
    entities = [f"E{index}" for index in range(8)]
    stored = [entity for entity in entities if entity not in {"E1", "E4"}]

    def one_run(limit: int) -> dict[str, object]:
        store = JanusStore(":memory:")
        source = EntityFailingSource({"E1", "E4"})
        result = IngestionScheduler(store, retries=1, max_concurrency=limit).run(
            source, entities, start, end
        )
        return {
            "counts": (result.fetched, result.stored, result.failed, result.dead_letters),
            "snapshot": _snapshot(store),
            "calls": dict(source.calls),
        }

    sequential = one_run(1)
    pooled = one_run(3)

    assert sequential["counts"] == (6, 6, 2, 2)
    assert pooled["counts"] == sequential["counts"]
    snapshot = pooled["snapshot"]
    assert snapshot["observations"] == [
        (f"entity-failing:{entity}", entity) for entity in stored
    ]
    assert [(row[0], row[1]) for row in snapshot["dead_letters"]] == [
        ("E1", "DataUnavailable: provider timeout"),
        ("E4", "DataUnavailable: provider timeout"),
    ]
    assert all(row[2] is None for row in snapshot["dead_letters"])
    assert snapshot["dead_letters"] == sequential["snapshot"]["dead_letters"]
    assert pooled["calls"] == sequential["calls"]
    assert pooled["calls"]["E1"] == 2 and pooled["calls"]["E4"] == 2


def test_run_row_always_finishes_with_its_counts() -> None:
    """AC8: finished_at, status and counts JSON hold at both limits and on error."""

    start, end = _window()
    for limit in (1, 3):
        store = JanusStore(":memory:")
        result = IngestionScheduler(store, max_concurrency=limit).run(
            FakeSource(), ["A", "B"], start, end
        )
        row = store.connection.execute(
            "SELECT status, counts, finished_at FROM ingestion_run"
        ).fetchone()
        assert row is not None
        assert row["finished_at"] is not None
        assert row["status"] == "completed"
        assert json.loads(row["counts"]) == {
            "fetched": result.fetched,
            "stored": result.stored,
            "failed": result.failed,
            "dead_letters": result.dead_letters,
        }

    store = JanusStore(":memory:")
    result = IngestionScheduler(store, retries=0, max_concurrency=3).run(
        ExplodingSource(), ["A", "B"], start, end
    )
    row = store.connection.execute(
        "SELECT status, counts, finished_at FROM ingestion_run"
    ).fetchone()
    assert row is not None
    assert row["finished_at"] is not None, "a worker exception left the run running"
    assert row["status"] == "partial"
    assert (result.stored, result.failed, result.dead_letters) == (1, 1, 1)
    assert json.loads(row["counts"]) == {
        "fetched": result.fetched,
        "stored": result.stored,
        "failed": result.failed,
        "dead_letters": result.dead_letters,
    }


def test_retries_stay_per_entity_sequential() -> None:
    """AC9: a retried entity is fetched twice, never two attempts in flight."""

    start, end = _window()
    source = FailOnceWithPeerSource()
    store = JanusStore(":memory:")
    result = IngestionScheduler(store, retries=1, max_concurrency=3).run(
        source, ["RETRY", "PEER"], start, end
    )

    assert (result.fetched, result.stored) == (2, 2)
    assert (result.failed, result.dead_letters) == (0, 0)
    assert source.calls == {"RETRY": 2, "PEER": 1}
    assert source.max_in_flight == {"RETRY": 1, "PEER": 1}


def test_store_failure_becomes_a_dead_letter(monkeypatch) -> None:
    store = JanusStore(":memory:")
    start, end = _window()
    scheduler = IngestionScheduler(store, retries=0)

    def boom(observation):
        raise RuntimeError("disk full")

    monkeypatch.setattr(store, "insert_observation", boom)
    result = scheduler.run(FakeSource(), ["ACME"], start, end)

    assert result.fetched == 1
    assert result.stored == 0
    assert result.failed == 1
    assert result.dead_letters == 1
    row = store.connection.execute(
        "SELECT status, counts FROM ingestion_run WHERE id = ?", (result.run_id,)
    ).fetchone()
    assert row["status"] == "partial"
    assert "disk full" in store.connection.execute(
        "SELECT error FROM ingestion_dead_letter"
    ).fetchone()["error"]


def test_store_failure_is_contained_in_pooled_mode(monkeypatch) -> None:
    store = JanusStore(":memory:")
    start, end = _window()
    scheduler = IngestionScheduler(store, retries=0, max_concurrency=2)

    def boom(observation):
        raise RuntimeError("disk full")

    monkeypatch.setattr(store, "insert_observation", boom)
    result = scheduler.run(FakeSource(), ["A", "B"], start, end)

    assert (result.fetched, result.stored, result.failed, result.dead_letters) == (
        2,
        0,
        2,
        2,
    )
