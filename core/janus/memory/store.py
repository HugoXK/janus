from __future__ import annotations

import functools
import json
from contextlib import contextmanager
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

from .encryption import KeyManager, KeyMissingError, Sealer, field_context
from .migrations import apply_migrations, current_version
from .models import (
    Observation,
    ObservationKind,
    Outcome,
    Persona,
    Prediction,
    Review,
    Thesis,
    ThesisStatus,
)


class _LockedConnection:
    """Serialize one SQLite connection across HTTP worker threads."""

    def __init__(self, connection: sqlite3.Connection, lock: threading.RLock) -> None:
        self._connection = connection
        self._lock = lock

    def execute(self, *args, **kwargs):
        with self._lock:
            return self._connection.execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        with self._lock:
            return self._connection.executemany(*args, **kwargs)

    def executescript(self, *args, **kwargs):
        with self._lock:
            return self._connection.executescript(*args, **kwargs)

    def commit(self) -> None:
        with self._lock:
            self._connection.commit()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self):
        self._lock.acquire()
        try:
            self._connection.__enter__()
        except BaseException:
            self._lock.release()
            raise
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            return self._connection.__exit__(exc_type, exc, tb)
        finally:
            self._lock.release()

    def __getattr__(self, name: str):
        return getattr(self._connection, name)


def _synchronized(method):
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


class JanusStore:
    """SQLite-backed point-in-time store.

    The store is intentionally small and local-first. The same interfaces can be
    backed by Postgres later without changing the domain models.
    """

    def __init__(
        self,
        path: Union[str, Path] = ":memory:",
        *,
        master_key: Optional[bytes] = None,
    ) -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        raw = sqlite3.connect(self.path, check_same_thread=False)
        raw.row_factory = sqlite3.Row
        raw.execute("PRAGMA foreign_keys = ON")
        self._conn = _LockedConnection(raw, self._lock)
        self.init_schema()
        self._master_key = master_key
        self._key_manager: Optional[KeyManager] = None
        self._sealer: Optional[Sealer] = None
        self._bootstrap_encryption()

    def _bootstrap_encryption(self) -> None:
        """Open an encrypted store only when its master key is available."""

        row = self._conn.execute("SELECT 1 FROM encryption_key LIMIT 1").fetchone()
        if row is not None:
            if self._master_key is None:
                raise KeyMissingError(
                    "this store is encrypted; set JANUS_MASTER_KEY or "
                    "JANUS_MASTER_KEY_FILE before opening it"
                )
            manager = KeyManager(self._conn, self._master_key)
            active = manager.active_key_id
            if active is None:
                raise KeyMissingError("encrypted store has no active data key")
            manager.dek(active)  # fail closed on a wrong master key
            self._key_manager = manager
            self._sealer = Sealer(manager)
        elif self._master_key is not None:
            self.enable_encryption()

    @property
    def encryption_enabled(self) -> bool:
        return self._sealer is not None

    @property
    def key_manager(self) -> Optional[KeyManager]:
        return self._key_manager

    @property
    def sealer(self) -> Optional[Sealer]:
        return self._sealer

    def enable_encryption(self) -> str:
        """Create the first data key for a store that has none yet."""

        if self._sealer is not None:
            return self._sealer.active_key_id
        if self._master_key is None:
            raise KeyMissingError(
                "no master key supplied; set JANUS_MASTER_KEY or JANUS_MASTER_KEY_FILE"
            )
        self._key_manager = KeyManager(self._conn, self._master_key)
        key_id = self._key_manager.ensure_key()
        self._sealer = Sealer(self._key_manager)
        return key_id

    def _seal_field(self, table: str, row_id: str, column: str, value: str) -> str:
        if self._sealer is None:
            return value
        return self._sealer.seal(
            value.encode("utf-8"), context=field_context(table, row_id, column)
        )

    def _unseal_field(
        self, key_id: Optional[str], table: str, row_id: str, column: str, value: str
    ) -> str:
        if key_id is None:
            return value
        if self._sealer is None:
            raise KeyMissingError("record is encrypted but the store has no master key")
        return self._sealer.unseal(
            value, context=field_context(table, row_id, column)
        ).decode("utf-8")

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn  # type: ignore[return-value]

    @property
    def _raw_connection(self) -> sqlite3.Connection:
        """Private escape hatch for sqlite3 APIs that reject the proxy object."""

        return self._conn._connection

    def init_schema(self) -> None:
        apply_migrations(self._conn)  # type: ignore[arg-type]

    @contextmanager
    def locked(self):
        """Hold the store lock for a multi-statement read or transaction."""

        with self._lock:
            yield self

    @property
    def schema_version(self) -> int:
        with self._lock:
            return current_version(self._conn)  # type: ignore[arg-type]

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------
    # Observations
    # ------------------------------------------------------------------
    def insert_observation(self, observation: Observation) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO observation
            (id, entity_id, kind, source, published_at, observed_at, valid_from,
             valid_to, value, unit, confidence, raw_hash, raw_uri, snapshot_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                observation.id,
                observation.entity_id,
                observation.kind.value,
                observation.source,
                observation.published_at.isoformat(),
                observation.observed_at.isoformat(),
                observation.valid_from.isoformat() if observation.valid_from else None,
                observation.valid_to.isoformat() if observation.valid_to else None,
                json.dumps(observation.value, sort_keys=True),
                observation.unit,
                observation.confidence,
                observation.raw_hash,
                observation.raw_uri,
                observation.snapshot_id,
            ),
        )
        self._conn.commit()

    def query_observations_as_of(
        self,
        entity_id: str,
        as_of: datetime,
        kind: Optional[ObservationKind] = None,
        *,
        mode: str = "published",
        snapshot_id: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> list[Observation]:
        """Return observations that were knowable at ``as_of``.

        ``mode="published"`` answers "what could the world have known?".
        ``mode="observed"`` answers "what had this system actually ingested?".
        The validity window is respected in both modes.
        """

        if mode not in {"published", "observed"}:
            raise ValueError("mode must be 'published' or 'observed'")
        if limit is not None and limit < 0:
            raise ValueError("limit must be >= 0")
        if offset < 0:
            raise ValueError("offset must be >= 0")

        time_column = "published_at" if mode == "published" else "observed_at"
        sql = f"""
            SELECT * FROM observation
            WHERE entity_id = ?
              AND {time_column} <= ?
              AND (valid_from IS NULL OR valid_from <= ?)
              AND (valid_to IS NULL OR valid_to > ?)
        """
        stamp = as_of.isoformat()
        params: list[object] = [entity_id, stamp, stamp, stamp]
        if kind is not None:
            sql += " AND kind = ?"
            params.append(kind.value)
        if snapshot_id is not None:
            sql += " AND snapshot_id = ?"
            params.append(snapshot_id)
        sql += f" ORDER BY {time_column} ASC, id ASC"
        sql += " LIMIT ? OFFSET ?"
        params.extend([limit if limit is not None else -1, offset])
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_observation(row) for row in rows]

    def get_observation(self, observation_id: str) -> Optional[Observation]:
        row = self._conn.execute(
            "SELECT * FROM observation WHERE id = ?", (observation_id,)
        ).fetchone()
        return self._row_to_observation(row) if row else None

    def search_observations(
        self,
        entity_id: str,
        text: str,
        as_of: datetime,
        limit: int = 20,
    ) -> list[Observation]:
        if limit < 0:
            raise ValueError("limit must be >= 0")
        stamp = as_of.isoformat()
        rows = self._conn.execute(
            """
            SELECT * FROM observation
            WHERE entity_id = ?
              AND value LIKE ?
              AND published_at <= ?
              AND (valid_from IS NULL OR valid_from <= ?)
              AND (valid_to IS NULL OR valid_to > ?)
            ORDER BY published_at DESC, id ASC
            LIMIT ?
            """,
            (entity_id, f"%{text}%", stamp, stamp, stamp, limit),
        ).fetchall()
        return [self._row_to_observation(row) for row in rows]

    @staticmethod
    def _row_to_observation(row: sqlite3.Row) -> Observation:
        return Observation(
            id=row["id"],
            entity_id=row["entity_id"],
            kind=ObservationKind(row["kind"]),
            source=row["source"],
            published_at=datetime.fromisoformat(row["published_at"]),
            observed_at=datetime.fromisoformat(row["observed_at"]),
            valid_from=datetime.fromisoformat(row["valid_from"]) if row["valid_from"] else None,
            valid_to=datetime.fromisoformat(row["valid_to"]) if row["valid_to"] else None,
            value=json.loads(row["value"]),
            unit=row["unit"],
            confidence=row["confidence"],
            raw_hash=row["raw_hash"],
            raw_uri=row["raw_uri"],
            snapshot_id=row["snapshot_id"],
        )

    # ------------------------------------------------------------------
    # Theses
    # ------------------------------------------------------------------
    def insert_thesis(self, thesis: Thesis) -> None:
        key_id = self._sealer.active_key_id if self._sealer is not None else None
        self._conn.execute(
            """
            INSERT INTO thesis
            (id, entity_id, persona_id, horizon, statement, assumptions, catalysts,
             risks, falsifiers, status, created_at, as_of, key_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                thesis.id,
                thesis.entity_id,
                thesis.persona_id,
                thesis.horizon,
                self._seal_field("thesis", thesis.id, "statement", thesis.statement),
                self._seal_field(
                    "thesis", thesis.id, "assumptions", json.dumps(thesis.assumptions)
                ),
                self._seal_field(
                    "thesis", thesis.id, "catalysts", json.dumps(thesis.catalysts)
                ),
                self._seal_field("thesis", thesis.id, "risks", json.dumps(thesis.risks)),
                self._seal_field(
                    "thesis", thesis.id, "falsifiers", json.dumps(thesis.falsifiers)
                ),
                thesis.status.value,
                thesis.created_at.isoformat(),
                thesis.as_of.isoformat(),
                key_id,
            ),
        )
        self._conn.commit()

    def get_thesis(self, thesis_id: str) -> Optional[Thesis]:
        row = self._conn.execute("SELECT * FROM thesis WHERE id = ?", (thesis_id,)).fetchone()
        return self._row_to_thesis(row) if row else None

    def update_thesis_status(self, thesis_id: str, status: ThesisStatus) -> None:
        self._conn.execute(
            "UPDATE thesis SET status = ? WHERE id = ?", (status.value, thesis_id)
        )
        self._conn.commit()

    def list_theses(self, status: Optional[ThesisStatus] = None) -> list[Thesis]:
        if status is None:
            rows = self._conn.execute("SELECT * FROM thesis ORDER BY created_at DESC").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM thesis WHERE status = ? ORDER BY created_at DESC",
                (status.value,),
            ).fetchall()
        return [self._row_to_thesis(row) for row in rows]

    def _row_to_thesis(self, row: sqlite3.Row) -> Thesis:
        key_id = row["key_id"]
        thesis_id = row["id"]

        def unseal(column: str) -> str:
            return self._unseal_field(key_id, "thesis", thesis_id, column, row[column])

        return Thesis(
            id=thesis_id,
            entity_id=row["entity_id"],
            persona_id=row["persona_id"],
            horizon=row["horizon"],
            statement=unseal("statement"),
            assumptions=json.loads(unseal("assumptions")),
            catalysts=json.loads(unseal("catalysts")),
            risks=json.loads(unseal("risks")),
            falsifiers=json.loads(unseal("falsifiers")),
            status=ThesisStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            as_of=datetime.fromisoformat(row["as_of"]),
        )

    # ------------------------------------------------------------------
    # Predictions and outcomes
    # ------------------------------------------------------------------
    def insert_prediction(
        self, prediction: Prediction, *, commit: bool = True
    ) -> None:
        key_id = self._sealer.active_key_id if self._sealer is not None else None
        self._conn.execute(
            """
            INSERT INTO prediction
            (id, thesis_id, target, horizon, probability, quantiles, model_version,
             features_hash, created_at, as_of, outcome_id, key_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                prediction.id,
                prediction.thesis_id,
                self._seal_field("prediction", prediction.id, "target", prediction.target),
                prediction.horizon,
                prediction.probability,
                json.dumps(prediction.quantiles, sort_keys=True),
                prediction.model_version,
                prediction.features_hash,
                prediction.created_at.isoformat(),
                prediction.as_of.isoformat(),
                prediction.outcome_id,
                key_id,
            ),
        )
        if commit:
            self._conn.commit()

    def get_prediction(self, prediction_id: str) -> Optional[Prediction]:
        row = self._conn.execute(
            "SELECT * FROM prediction WHERE id = ?", (prediction_id,)
        ).fetchone()
        return self._row_to_prediction(row) if row else None

    def list_predictions(
        self, thesis_id: Optional[str] = None, open_only: bool = False
    ) -> list[Prediction]:
        sql = "SELECT * FROM prediction"
        clauses: list[str] = []
        params: list[object] = []
        if thesis_id is not None:
            clauses.append("thesis_id = ?")
            params.append(thesis_id)
        if open_only:
            clauses.append("outcome_id IS NULL")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC"
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_prediction(row) for row in rows]

    def attach_outcome(
        self, prediction_id: str, outcome_id: str, *, commit: bool = True
    ) -> None:
        """Attach an outcome. This is the only mutation allowed on a prediction."""

        self._conn.execute(
            "UPDATE prediction SET outcome_id = ? WHERE id = ?", (outcome_id, prediction_id)
        )
        if commit:
            self._conn.commit()

    def insert_outcome(
        self, outcome: Outcome, *, commit: bool = True
    ) -> None:
        key_id = self._sealer.active_key_id if self._sealer is not None else None
        self._conn.execute(
            """
            INSERT INTO outcome
            (id, prediction_id, realized_value, realized_at, source, score, key_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                outcome.id,
                outcome.prediction_id,
                self._seal_field(
                    "outcome",
                    outcome.id,
                    "realized_value",
                    json.dumps(outcome.realized_value, sort_keys=True),
                ),
                outcome.realized_at.isoformat(),
                outcome.source,
                outcome.score,
                key_id,
            ),
        )
        if commit:
            self._conn.commit()

    def get_outcome(self, outcome_id: str) -> Optional[Outcome]:
        row = self._conn.execute("SELECT * FROM outcome WHERE id = ?", (outcome_id,)).fetchone()
        return self._row_to_outcome(row) if row else None

    def list_outcomes(self) -> list[Outcome]:
        rows = self._conn.execute(
            "SELECT * FROM outcome ORDER BY realized_at DESC"
        ).fetchall()
        return [self._row_to_outcome(row) for row in rows]

    def settled_predictions(self) -> list[tuple[Prediction, Outcome]]:
        rows = self._conn.execute(
            "SELECT * FROM prediction WHERE outcome_id IS NOT NULL ORDER BY as_of DESC"
        ).fetchall()
        pairs: list[tuple[Prediction, Outcome]] = []
        for row in rows:
            prediction = self._row_to_prediction(row)
            if prediction.outcome_id is None:
                continue
            outcome = self.get_outcome(prediction.outcome_id)
            if outcome is not None:
                pairs.append((prediction, outcome))
        return pairs

    def _row_to_prediction(self, row: sqlite3.Row) -> Prediction:
        return Prediction(
            id=row["id"],
            thesis_id=row["thesis_id"],
            target=self._unseal_field(
                row["key_id"], "prediction", row["id"], "target", row["target"]
            ),
            horizon=row["horizon"],
            probability=row["probability"],
            quantiles=json.loads(row["quantiles"]),
            model_version=row["model_version"],
            features_hash=row["features_hash"],
            created_at=datetime.fromisoformat(row["created_at"]),
            as_of=datetime.fromisoformat(row["as_of"]),
            outcome_id=row["outcome_id"],
        )

    def _row_to_outcome(self, row: sqlite3.Row) -> Outcome:
        return Outcome(
            id=row["id"],
            prediction_id=row["prediction_id"],
            realized_value=json.loads(
                self._unseal_field(
                    row["key_id"], "outcome", row["id"], "realized_value", row["realized_value"]
                )
            ),
            realized_at=datetime.fromisoformat(row["realized_at"]),
            source=row["source"],
            score=row["score"],
        )

    # ------------------------------------------------------------------
    # Personas and reviews
    # ------------------------------------------------------------------
    def insert_persona(self, persona: Persona) -> None:
        self._conn.execute(
            """
            INSERT INTO persona
            (id, name, profile, weights, rules, version, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                persona.id,
                persona.name,
                json.dumps(persona.profile, sort_keys=True),
                json.dumps(persona.weights, sort_keys=True),
                json.dumps(persona.rules, sort_keys=True),
                persona.version,
                persona.created_at.isoformat(),
            ),
        )
        self._conn.commit()

    def get_persona(self, persona_id: str) -> Optional[Persona]:
        row = self._conn.execute("SELECT * FROM persona WHERE id = ?", (persona_id,)).fetchone()
        return self._row_to_persona(row) if row else None

    def list_personas(self) -> list[Persona]:
        rows = self._conn.execute(
            "SELECT * FROM persona ORDER BY created_at DESC"
        ).fetchall()
        return [self._row_to_persona(row) for row in rows]

    def insert_review(self, review: Review) -> None:
        self._conn.execute(
            """
            INSERT INTO review
            (id, prediction_id, attribution, calibration, lessons, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                review.id,
                review.prediction_id,
                json.dumps(review.attribution, sort_keys=True),
                review.calibration,
                review.lessons,
                review.created_at.isoformat(),
            ),
        )
        self._conn.commit()

    def list_reviews(self, prediction_id: Optional[str] = None) -> list[Review]:
        if prediction_id is None:
            rows = self._conn.execute("SELECT * FROM review ORDER BY created_at DESC").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM review WHERE prediction_id = ? ORDER BY created_at DESC",
                (prediction_id,),
            ).fetchall()
        return [self._row_to_review(row) for row in rows]

    @staticmethod
    def _row_to_persona(row: sqlite3.Row) -> Persona:
        return Persona(
            id=row["id"],
            name=row["name"],
            profile=json.loads(row["profile"]),
            weights=json.loads(row["weights"]),
            rules=json.loads(row["rules"]),
            version=row["version"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _row_to_review(row: sqlite3.Row) -> Review:
        return Review(
            id=row["id"],
            prediction_id=row["prediction_id"],
            attribution=json.loads(row["attribution"]),
            calibration=row["calibration"],
            lessons=row["lessons"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )


for _method_name, _method in list(vars(JanusStore).items()):
    if (
        callable(_method)
        and not _method_name.startswith("_")
        and _method_name != "locked"
    ):
        setattr(JanusStore, _method_name, _synchronized(_method))
