from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

INITIAL_SCHEMA = """
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

MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    applied_at  TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


MIGRATIONS: list[Migration] = [
    Migration(version=1, name="initial", sql=INITIAL_SCHEMA),
]


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def ensure_migrations_table(connection: sqlite3.Connection) -> None:
    connection.executescript(MIGRATIONS_TABLE)
    connection.commit()


def applied_versions(connection: sqlite3.Connection) -> list[int]:
    if not _table_exists(connection, "schema_migrations"):
        return []
    rows = connection.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    ).fetchall()
    return [int(row[0]) for row in rows]


def current_version(connection: sqlite3.Connection) -> int:
    versions = applied_versions(connection)
    return max(versions) if versions else 0


def apply_migrations(
    connection: sqlite3.Connection, dry_run: bool = False
) -> list[int]:
    """Apply pending migrations and return the versions that were applied.

    In dry-run mode nothing is written; the return value is the list of versions
    that would be applied.
    """

    applied = set(applied_versions(connection))
    pending = [migration for migration in MIGRATIONS if migration.version not in applied]
    if dry_run:
        return [migration.version for migration in pending]

    ensure_migrations_table(connection)
    applied_now: list[int] = []
    for migration in pending:
        connection.executescript(migration.sql)
        connection.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
            (migration.version, migration.name, datetime.now(timezone.utc).isoformat()),
        )
        connection.commit()
        applied_now.append(migration.version)
    return applied_now


def migrate(
    path: Union[str, Path], dry_run: bool = False
) -> tuple[list[int], int]:
    """Apply migrations to a database path and return (applied, version)."""

    connection = sqlite3.connect(str(path))
    try:
        applied = apply_migrations(connection, dry_run=dry_run)
        return applied, current_version(connection)
    finally:
        connection.close()


def migration_status(connection: sqlite3.Connection) -> dict[str, Optional[object]]:
    return {
        "current": current_version(connection),
        "latest": max(migration.version for migration in MIGRATIONS),
    }
