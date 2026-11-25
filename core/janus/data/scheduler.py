from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from ..memory.models import Observation, utcnow
from ..memory.store import JanusStore
from ..logging import log_event
from .base import DataSource


@dataclass(frozen=True)
class IngestionResult:
    run_id: str
    source: str
    fetched: int
    stored: int
    failed: int
    dead_letters: int


@dataclass(frozen=True)
class ReplayResult:
    replayed: int
    failed: int


@dataclass(frozen=True)
class _FetchOutcome:
    """One entity's fetch after its per-entity retries are exhausted.

    Exactly one of ``observations`` and ``error`` is meaningful: ``error`` is
    ``None`` when the entity was fetched, and the recorded dead-letter reason
    otherwise. A worker builds this and never touches the store.
    """

    observations: list[Observation]
    error: str | None = None


class IngestionScheduler:
    """Run a source over entities with retries, a dead-letter queue, and a report.

    ``max_concurrency`` bounds how many ``source.fetch`` calls may be in flight
    at once. Only fetching is pooled: every store write happens on the thread
    that called ``run``, in input entity order, because the SQLite connection is
    not shared across threads. A pooled run holds one run's observations in
    memory until collection finishes, so the peak is one run's payload.
    """

    def __init__(
        self,
        store: JanusStore,
        *,
        retries: int = 3,
        backoff_seconds: float = 0.0,
        max_concurrency: int = 1,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError(f"max_concurrency must be >= 1, got {max_concurrency}")
        self.store = store
        self.retries = retries
        self.backoff_seconds = backoff_seconds
        self.max_concurrency = max_concurrency

    def run(
        self,
        source: DataSource,
        entities: list[str],
        start: datetime,
        end: datetime,
    ) -> IngestionResult:
        run_id = uuid4().hex
        started_at = utcnow().isoformat()
        self.store.connection.execute(
            """
            INSERT INTO ingestion_run (id, source, started_at, status, counts)
            VALUES (?, ?, ?, 'running', '{}')
            """,
            (run_id, source.name, started_at),
        )
        self.store.connection.commit()
        log_event(
            "ingestion.start",
            run_id=run_id,
            source=source.name,
            entities=len(entities),
            as_of=end.isoformat(),
        )

        if self.max_concurrency == 1:
            counts = self._run_sequential(run_id, source, entities, start, end)
        else:
            counts = self._run_pooled(run_id, source, entities, start, end)

        status = "completed" if counts["failed"] == 0 else "partial"
        self.store.connection.execute(
            """
            UPDATE ingestion_run
            SET finished_at = ?, status = ?, counts = ?
            WHERE id = ?
            """,
            (utcnow().isoformat(), status, json.dumps(counts, sort_keys=True), run_id),
        )
        self.store.connection.commit()
        log_event(
            "ingestion.complete",
            run_id=run_id,
            source=source.name,
            status=status,
            as_of=end.isoformat(),
            **counts,
        )
        return IngestionResult(
            run_id=run_id,
            source=source.name,
            fetched=counts["fetched"],
            stored=counts["stored"],
            failed=counts["failed"],
            dead_letters=counts["dead_letters"],
        )

    def _run_sequential(
        self,
        run_id: str,
        source: DataSource,
        entities: list[str],
        start: datetime,
        end: datetime,
    ) -> dict[str, int]:
        """The pre-existing path: fetch, persist, then move to the next entity."""

        fetched = stored = failed = dead_letters = 0
        for entity_id in entities:
            outcome = self._fetch_with_retries(source, entity_id, start, end)
            if outcome.error is not None:
                failed += 1
                dead_letters += 1
                self._record_dead_letter(run_id, source.name, entity_id, outcome.error)
                log_event(
                    "ingestion.dead_letter",
                    level=logging.ERROR,
                    run_id=run_id,
                    source=source.name,
                    entity_id=entity_id,
                    as_of=end.isoformat(),
                    error=outcome.error,
                )
                continue
            fetched += len(outcome.observations)
            for observation in outcome.observations:
                self.store.insert_observation(observation)
            stored += len(outcome.observations)
        return {
            "fetched": fetched,
            "stored": stored,
            "failed": failed,
            "dead_letters": dead_letters,
        }

    def _run_pooled(
        self,
        run_id: str,
        source: DataSource,
        entities: list[str],
        start: datetime,
        end: datetime,
    ) -> dict[str, int]:
        """Pool ``source.fetch`` only, then persist on this thread in input order.

        Results are collected with ``future.result()`` in submission order, so
        counts, row order and dead-letter order never depend on which fetch
        finishes first. ``_fetch_with_retries`` returns failures instead of
        raising, so no worker exception reaches ``future.result()`` and the run
        row always gets its final status.
        """

        with ThreadPoolExecutor(
            max_workers=self.max_concurrency,
            thread_name_prefix="janus-ingest",
        ) as pool:
            futures = [
                pool.submit(self._fetch_with_retries, source, entity_id, start, end)
                for entity_id in entities
            ]
            outcomes = [future.result() for future in futures]

        fetched = stored = failed = dead_letters = 0
        for entity_id, outcome in zip(entities, outcomes):
            if outcome.error is not None:
                failed += 1
                dead_letters += 1
                self._record_dead_letter(run_id, source.name, entity_id, outcome.error)
                log_event(
                    "ingestion.dead_letter",
                    level=logging.ERROR,
                    run_id=run_id,
                    source=source.name,
                    entity_id=entity_id,
                    as_of=end.isoformat(),
                    error=outcome.error,
                )
                continue
            fetched += len(outcome.observations)
            for observation in outcome.observations:
                self.store.insert_observation(observation)
            stored += len(outcome.observations)
        return {
            "fetched": fetched,
            "stored": stored,
            "failed": failed,
            "dead_letters": dead_letters,
        }

    def _fetch_with_retries(
        self,
        source: DataSource,
        entity_id: str,
        start: datetime,
        end: datetime,
    ) -> _FetchOutcome:
        """Fetch one entity, retrying that entity only; never raises on failure."""

        for attempt in range(self.retries + 1):
            try:
                observations = source.fetch(entity_id, start, end)
            except Exception as exc:  # noqa: BLE001 - source boundary
                if attempt >= self.retries:
                    return _FetchOutcome(
                        observations=[],
                        error=f"{type(exc).__name__}: {exc}",
                    )
                if self.backoff_seconds:
                    time.sleep(self.backoff_seconds * (2**attempt))
                continue
            return _FetchOutcome(observations=observations, error=None)
        raise AssertionError("unreachable: retry loop always returns")

    def _record_dead_letter(
        self,
        run_id: str,
        source_name: str,
        entity_id: str,
        error: str,
    ) -> None:
        self.store.connection.execute(
            """
            INSERT INTO ingestion_dead_letter
            (run_id, source, entity_id, error, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                run_id,
                source_name,
                entity_id,
                error,
                utcnow().isoformat(),
            ),
        )
        self.store.connection.commit()

    def replay(
        self,
        source: DataSource,
        start: datetime,
        end: datetime,
    ) -> ReplayResult:
        rows = self.store.connection.execute(
            """
            SELECT id, entity_id FROM ingestion_dead_letter
            WHERE source = ? AND replayed_at IS NULL
            ORDER BY id
            """,
            (source.name,),
        ).fetchall()
        replayed = failed = 0
        for row in rows:
            try:
                observations = source.fetch(str(row["entity_id"]), start, end)
            except Exception:
                failed += 1
                continue
            for observation in observations:
                self.store.insert_observation(observation)
            self.store.connection.execute(
                "UPDATE ingestion_dead_letter SET replayed_at = ? WHERE id = ?",
                (utcnow().isoformat(), row["id"]),
            )
            self.store.connection.commit()
            replayed += 1
        return ReplayResult(replayed=replayed, failed=failed)
