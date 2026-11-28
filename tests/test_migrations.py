from __future__ import annotations

import sqlite3

from janus.memory.migrations import LATEST_VERSION, apply_migrations, current_version
from janus.memory.store import JanusStore


def _tables(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {str(row[0]) for row in rows}


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row[1]) for row in rows}


def test_fresh_store_has_the_current_schema() -> None:
    store = JanusStore(":memory:")
    assert store.schema_version == LATEST_VERSION
    assert "schema_migrations" in _tables(store._conn)
    assert "observation" in _tables(store._conn)
    assert "entity" in _tables(store._conn)
    assert "entity_alias" in _tables(store._conn)
    assert "feature_value" in _tables(store._conn)
    assert "ingestion_run" in _tables(store._conn)
    assert "ingestion_dead_letter" in _tables(store._conn)
    assert "security" in _tables(store._conn)
    assert "universe_membership" in _tables(store._conn)
    assert "corporate_action" in _tables(store._conn)
    assert "source_span" in _tables(store._conn)
    assert "audit_entry" in _tables(store._conn)
    assert "mcp_approval" in _tables(store._conn)
    assert "mcp_audit" in _tables(store._conn)
    assert "encryption_key" in _tables(store._conn)
    assert "encryption_rotation" in _tables(store._conn)
    assert "key_id" in _columns(store._conn, "thesis")
    assert "key_id" in _columns(store._conn, "prediction")
    assert "key_id" in _columns(store._conn, "outcome")
    assert "share_request" in _tables(store._conn)
    assert "share_audit" in _tables(store._conn)
    assert "snapshot_id" in _columns(store._conn, "observation")


def test_migrations_are_idempotent() -> None:
    connection = sqlite3.connect(":memory:")
    assert apply_migrations(connection) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
    assert apply_migrations(connection) == []
    assert current_version(connection) == LATEST_VERSION


def test_dry_run_does_not_write() -> None:
    connection = sqlite3.connect(":memory:")
    assert apply_migrations(connection, dry_run=True) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
    assert current_version(connection) == 0
    assert "observation" not in _tables(connection)
    assert "schema_migrations" not in _tables(connection)


def test_applied_versions_are_recorded() -> None:
    connection = sqlite3.connect(":memory:")
    apply_migrations(connection)
    rows = connection.execute(
        "SELECT version, name FROM schema_migrations ORDER BY version"
    ).fetchall()
    assert [(row[0], row[1]) for row in rows] == [
        (1, "initial"),
        (2, "observation_snapshot"),
        (3, "entity_graph"),
        (4, "feature_store"),
        (5, "ingestion"),
        (6, "security_master"),
        (7, "corporate_actions"),
        (8, "source_spans"),
        (9, "audit_chain"),
        (10, "mcp_scoped_auth"),
        (11, "encryption_at_rest"),
        (12, "sharing"),
    ]
