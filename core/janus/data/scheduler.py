from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from ..memory.models import utcnow
from ..memory.store import JanusStore
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


class IngestionScheduler:
    """Run a source over entities with retries, a dead-letter queue, and a report."""

    def __init__(
        self,
        store: JanusStore,
        *,
        retries: int = 3,
        backoff_seconds: float = 0.0,
    ) -> None:
        self.store = store
        self.retries = retries
        self.backoff_seconds = backoff_seconds

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

        fetched = stored = failed = dead_letters = 0
        for entity_id in entities:
            for attempt in range(self.retries + 1):
                try:
                    observations = source.fetch(entity_id, start, end)
                except Exception as exc:  # noqa: BLE001 - source boundary
                    if attempt >= self.retries:
                        failed += 1
                        dead_letters += 1
                        self.store.connection.execute(
                            """
                            INSERT INTO ingestion_dead_letter
                            (run_id, source, entity_id, error, created_at)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (
                                run_id,
                                source.name,
                                entity_id,
                                f"{type(exc).__name__}: {exc}",
                                utcnow().isoformat(),
                            ),
                        )
                        self.store.connection.commit()
                        break
                    if self.backoff_seconds:
                        time.sleep(self.backoff_seconds * (2**attempt))
                    continue
                fetched += len(observations)
                for observation in observations:
                    self.store.insert_observation(observation)
                stored += len(observations)
                break

        counts: dict[str, Any] = {
            "fetched": fetched,
            "stored": stored,
            "failed": failed,
            "dead_letters": dead_letters,
        }
        status = "completed" if failed == 0 else "partial"
        self.store.connection.execute(
            """
            UPDATE ingestion_run
            SET finished_at = ?, status = ?, counts = ?
            WHERE id = ?
            """,
            (utcnow().isoformat(), status, json.dumps(counts, sort_keys=True), run_id),
        )
        self.store.connection.commit()
        return IngestionResult(
            run_id=run_id,
            source=source.name,
            fetched=fetched,
            stored=stored,
            failed=failed,
            dead_letters=dead_letters,
        )

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
