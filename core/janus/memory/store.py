from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

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

SCHEMA = """
CREATE TABLE IF NOT EXISTS observation (
    id            TEXT PRIMARY KEY,
    entity_id     TEXT NOT NULL,
    kind          TEXT NOT NULL,
    source        TEXT NOT NULL,
    published_at  TEXT NOT NULL,
    observed_at   TEXT NOT NULL,
    valid_from    TEXT,
    valid_to      TEXT,
    value         TEXT NOT NULL,
    unit          TEXT,
    confidence    REAL NOT NULL,
    raw_hash      TEXT NOT NULL,
    raw_uri       TEXT
);
CREATE INDEX IF NOT EXISTS idx_observation_entity_published
    ON observation(entity_id, published_at);
CREATE INDEX IF NOT EXISTS idx_observation_kind
    ON observation(kind);

CREATE TABLE IF NOT EXISTS thesis (
    id            TEXT PRIMARY KEY,
    entity_id     TEXT NOT NULL,
    persona_id    TEXT,
    horizon       TEXT NOT NULL,
    statement     TEXT NOT NULL,
    assumptions   TEXT NOT NULL DEFAULT '[]',
    catalysts     TEXT NOT NULL DEFAULT '[]',
    risks         TEXT NOT NULL DEFAULT '[]',
    falsifiers    TEXT NOT NULL DEFAULT '[]',
    status        TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    as_of         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_thesis_entity ON thesis(entity_id);
CREATE INDEX IF NOT EXISTS idx_thesis_status ON thesis(status);

CREATE TABLE IF NOT EXISTS prediction (
    id             TEXT PRIMARY KEY,
    thesis_id      TEXT NOT NULL,
    target         TEXT NOT NULL,
    horizon        TEXT NOT NULL,
    probability    REAL,
    quantiles      TEXT NOT NULL DEFAULT '{}',
    model_version  TEXT NOT NULL,
    features_hash  TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    as_of          TEXT NOT NULL,
    outcome_id     TEXT
);
CREATE INDEX IF NOT EXISTS idx_prediction_thesis ON prediction(thesis_id);
CREATE INDEX IF NOT EXISTS idx_prediction_open ON prediction(outcome_id);

CREATE TABLE IF NOT EXISTS outcome (
    id              TEXT PRIMARY KEY,
    prediction_id   TEXT NOT NULL,
    realized_value  TEXT NOT NULL,
    realized_at     TEXT NOT NULL,
    source          TEXT NOT NULL,
    score           REAL
);
CREATE INDEX IF NOT EXISTS idx_outcome_prediction ON outcome(prediction_id);

CREATE TABLE IF NOT EXISTS persona (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    profile       TEXT NOT NULL,
    weights       TEXT NOT NULL,
    rules         TEXT NOT NULL DEFAULT '{}',
    version       TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review (
    id             TEXT PRIMARY KEY,
    prediction_id  TEXT NOT NULL,
    attribution    TEXT NOT NULL,
    calibration    REAL,
    lessons        TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_review_prediction ON review(prediction_id);
"""


class JanusStore:
    """SQLite-backed point-in-time store.

    The store is intentionally small and local-first. The same interfaces can be
    backed by Postgres later without changing the domain models.
    """

    def __init__(self, path: Union[str, Path] = ":memory:") -> None:
        self.path = str(path)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self.init_schema()

    def init_schema(self) -> None:
        self._conn.executescript(SCHEMA)
        self._conn.commit()

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
             valid_to, value, unit, confidence, raw_hash, raw_uri)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        self._conn.commit()

    def query_observations_as_of(
        self,
        entity_id: str,
        as_of: datetime,
        kind: Optional[ObservationKind] = None,
    ) -> list[Observation]:
        """Return observations that were published and valid at ``as_of``.

        This is the core anti-lookahead query. Future observations are never
        returned, even if they are already in the local database.
        """

        sql = """
            SELECT * FROM observation
            WHERE entity_id = ?
              AND published_at <= ?
              AND (valid_from IS NULL OR valid_from <= ?)
              AND (valid_to IS NULL OR valid_to > ?)
        """
        stamp = as_of.isoformat()
        params: list[object] = [entity_id, stamp, stamp, stamp]
        if kind is not None:
            sql += " AND kind = ?"
            params.append(kind.value)
        sql += " ORDER BY published_at ASC, id ASC"
        rows = self._conn.execute(sql, params).fetchall()
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
        )

    # ------------------------------------------------------------------
    # Theses
    # ------------------------------------------------------------------
    def insert_thesis(self, thesis: Thesis) -> None:
        self._conn.execute(
            """
            INSERT INTO thesis
            (id, entity_id, persona_id, horizon, statement, assumptions, catalysts,
             risks, falsifiers, status, created_at, as_of)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                thesis.id,
                thesis.entity_id,
                thesis.persona_id,
                thesis.horizon,
                thesis.statement,
                json.dumps(thesis.assumptions),
                json.dumps(thesis.catalysts),
                json.dumps(thesis.risks),
                json.dumps(thesis.falsifiers),
                thesis.status.value,
                thesis.created_at.isoformat(),
                thesis.as_of.isoformat(),
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

    @staticmethod
    def _row_to_thesis(row: sqlite3.Row) -> Thesis:
        return Thesis(
            id=row["id"],
            entity_id=row["entity_id"],
            persona_id=row["persona_id"],
            horizon=row["horizon"],
            statement=row["statement"],
            assumptions=json.loads(row["assumptions"]),
            catalysts=json.loads(row["catalysts"]),
            risks=json.loads(row["risks"]),
            falsifiers=json.loads(row["falsifiers"]),
            status=ThesisStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            as_of=datetime.fromisoformat(row["as_of"]),
        )

    # ------------------------------------------------------------------
    # Predictions and outcomes
    # ------------------------------------------------------------------
    def insert_prediction(self, prediction: Prediction) -> None:
        self._conn.execute(
            """
            INSERT INTO prediction
            (id, thesis_id, target, horizon, probability, quantiles, model_version,
             features_hash, created_at, as_of, outcome_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                prediction.id,
                prediction.thesis_id,
                prediction.target,
                prediction.horizon,
                prediction.probability,
                json.dumps(prediction.quantiles, sort_keys=True),
                prediction.model_version,
                prediction.features_hash,
                prediction.created_at.isoformat(),
                prediction.as_of.isoformat(),
                prediction.outcome_id,
            ),
        )
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

    def attach_outcome(self, prediction_id: str, outcome_id: str) -> None:
        """Attach an outcome. This is the only mutation allowed on a prediction."""

        self._conn.execute(
            "UPDATE prediction SET outcome_id = ? WHERE id = ?", (outcome_id, prediction_id)
        )
        self._conn.commit()

    def insert_outcome(self, outcome: Outcome) -> None:
        self._conn.execute(
            """
            INSERT INTO outcome
            (id, prediction_id, realized_value, realized_at, source, score)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                outcome.id,
                outcome.prediction_id,
                json.dumps(outcome.realized_value, sort_keys=True),
                outcome.realized_at.isoformat(),
                outcome.source,
                outcome.score,
            ),
        )
        self._conn.commit()

    def get_outcome(self, outcome_id: str) -> Optional[Outcome]:
        row = self._conn.execute("SELECT * FROM outcome WHERE id = ?", (outcome_id,)).fetchone()
        return self._row_to_outcome(row) if row else None

    @staticmethod
    def _row_to_prediction(row: sqlite3.Row) -> Prediction:
        return Prediction(
            id=row["id"],
            thesis_id=row["thesis_id"],
            target=row["target"],
            horizon=row["horizon"],
            probability=row["probability"],
            quantiles=json.loads(row["quantiles"]),
            model_version=row["model_version"],
            features_hash=row["features_hash"],
            created_at=datetime.fromisoformat(row["created_at"]),
            as_of=datetime.fromisoformat(row["as_of"]),
            outcome_id=row["outcome_id"],
        )

    @staticmethod
    def _row_to_outcome(row: sqlite3.Row) -> Outcome:
        return Outcome(
            id=row["id"],
            prediction_id=row["prediction_id"],
            realized_value=json.loads(row["realized_value"]),
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
