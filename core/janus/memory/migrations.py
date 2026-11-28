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
    Migration(
        version=2,
        name="observation_snapshot",
        sql="""
        ALTER TABLE observation ADD COLUMN snapshot_id TEXT;
        CREATE INDEX IF NOT EXISTS idx_observation_entity_observed
            ON observation(entity_id, observed_at);
        CREATE INDEX IF NOT EXISTS idx_observation_snapshot
            ON observation(snapshot_id);
        """,
    ),
    Migration(
        version=3,
        name="entity_graph",
        sql="""
        CREATE TABLE IF NOT EXISTS entity (
            id        TEXT PRIMARY KEY,
            name      TEXT NOT NULL,
            ticker    TEXT,
            cik       TEXT,
            sector    TEXT,
            industry  TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_entity_ticker
            ON entity(ticker) WHERE ticker IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_entity_cik
            ON entity(cik) WHERE cik IS NOT NULL;

        CREATE TABLE IF NOT EXISTS entity_alias (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            alias       TEXT NOT NULL,
            normalized  TEXT NOT NULL UNIQUE,
            entity_id   TEXT NOT NULL,
            source      TEXT NOT NULL,
            FOREIGN KEY(entity_id) REFERENCES entity(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_entity_alias_entity
            ON entity_alias(entity_id);
        """,
    ),
    Migration(
        version=4,
        name="feature_store",
        sql="""
        CREATE TABLE IF NOT EXISTS feature_value (
            entity_id      TEXT NOT NULL,
            as_of          TEXT NOT NULL,
            name           TEXT NOT NULL,
            version        TEXT NOT NULL,
            value          TEXT NOT NULL,
            features_hash  TEXT NOT NULL,
            source_hash    TEXT NOT NULL DEFAULT '',
            computed_at    TEXT NOT NULL,
            PRIMARY KEY (entity_id, as_of, name, version)
        );
        CREATE INDEX IF NOT EXISTS idx_feature_entity_asof
            ON feature_value(entity_id, as_of);
        """,
    ),
    Migration(
        version=5,
        name="ingestion",
        sql="""
        CREATE TABLE IF NOT EXISTS ingestion_run (
            id          TEXT PRIMARY KEY,
            source      TEXT NOT NULL,
            started_at  TEXT NOT NULL,
            finished_at TEXT,
            status      TEXT NOT NULL,
            counts      TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_ingestion_run_source
            ON ingestion_run(source, started_at);

        CREATE TABLE IF NOT EXISTS ingestion_dead_letter (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id      TEXT NOT NULL,
            source      TEXT NOT NULL,
            entity_id   TEXT NOT NULL,
            error       TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            replayed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_dead_letter_source
            ON ingestion_dead_letter(source, replayed_at);
        """,
    ),
    Migration(
        version=6,
        name="security_master",
        sql="""
        CREATE TABLE IF NOT EXISTS security (
            id           TEXT PRIMARY KEY,
            entity_id    TEXT NOT NULL,
            symbol       TEXT NOT NULL,
            exchange     TEXT NOT NULL DEFAULT '',
            currency     TEXT NOT NULL DEFAULT '',
            share_class  TEXT NOT NULL DEFAULT '',
            valid_from   TEXT NOT NULL,
            valid_to     TEXT,
            source       TEXT NOT NULL DEFAULT 'manual'
        );
        CREATE INDEX IF NOT EXISTS idx_security_symbol
            ON security(symbol, valid_from, valid_to);
        CREATE INDEX IF NOT EXISTS idx_security_entity
            ON security(entity_id);

        CREATE TABLE IF NOT EXISTS universe_membership (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            universe     TEXT NOT NULL,
            security_id  TEXT NOT NULL,
            valid_from   TEXT NOT NULL,
            valid_to     TEXT,
            source       TEXT NOT NULL DEFAULT 'manual',
            FOREIGN KEY(security_id) REFERENCES security(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_universe_membership
            ON universe_membership(universe, valid_from, valid_to);
        CREATE INDEX IF NOT EXISTS idx_universe_security
            ON universe_membership(security_id);
        """,
    ),
    Migration(
        version=7,
        name="corporate_actions",
        sql="""
        CREATE TABLE IF NOT EXISTS corporate_action (
            id                   TEXT PRIMARY KEY,
            security_id          TEXT NOT NULL,
            action_type          TEXT NOT NULL,
            effective_at         TEXT NOT NULL,
            ratio                REAL,
            cash_amount          REAL,
            currency             TEXT NOT NULL DEFAULT '',
            related_security_id  TEXT,
            source               TEXT NOT NULL DEFAULT 'manual',
            raw_hash             TEXT NOT NULL DEFAULT '',
            payload              TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_corporate_action_security
            ON corporate_action(security_id, effective_at);
        """,
    ),
    Migration(
        version=8,
        name="source_spans",
        sql="""
        CREATE TABLE IF NOT EXISTS source_span (
            id             TEXT PRIMARY KEY,
            observation_id TEXT NOT NULL,
            blob_hash      TEXT NOT NULL,
            locator        TEXT NOT NULL,
            excerpt        TEXT NOT NULL,
            start_offset   INTEGER,
            end_offset     INTEGER,
            source         TEXT NOT NULL DEFAULT 'manual',
            created_at     TEXT NOT NULL,
            FOREIGN KEY(observation_id) REFERENCES observation(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_source_span_observation
            ON source_span(observation_id, locator);
        """,
    ),
    Migration(
        version=9,
        name="audit_chain",
        sql="""
        CREATE TABLE IF NOT EXISTS audit_entry (
            seq          INTEGER PRIMARY KEY,
            kind         TEXT NOT NULL,
            ref_id       TEXT NOT NULL,
            recorded_at  TEXT NOT NULL,
            payload      TEXT NOT NULL,
            prev_hash    TEXT NOT NULL,
            entry_hash   TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_audit_entry_kind
            ON audit_entry(kind, seq);
        CREATE TRIGGER IF NOT EXISTS audit_entry_no_update
        BEFORE UPDATE ON audit_entry
        BEGIN
            SELECT RAISE(ABORT, 'audit_entry is append-only');
        END;
        CREATE TRIGGER IF NOT EXISTS audit_entry_no_delete
        BEFORE DELETE ON audit_entry
        BEGIN
            SELECT RAISE(ABORT, 'audit_entry is append-only');
        END;
        """,
    ),
]

LATEST_VERSION = max(migration.version for migration in MIGRATIONS)


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
        "latest": LATEST_VERSION,
    }
