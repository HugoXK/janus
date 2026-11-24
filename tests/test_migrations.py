from __future__ import annotations

import sqlite3

from janus.memory.migrations import apply_migrations, current_version
from janus.memory.store import JanusStore


def _tables(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {str(row[0]) for row in rows}


def test_fresh_store_has_the_current_schema() -> None:
    store = JanusStore(":memory:")
    assert store.schema_version == 1
    assert "schema_migrations" in _tables(store._conn)
    assert "observation" in _tables(store._conn)


def test_migrations_are_idempotent() -> None:
    connection = sqlite3.connect(":memory:")
    assert apply_migrations(connection) == [1]
    assert apply_migrations(connection) == []
    assert current_version(connection) == 1


def test_dry_run_does_not_write() -> None:
    connection = sqlite3.connect(":memory:")
    assert apply_migrations(connection, dry_run=True) == [1]
    assert current_version(connection) == 0
    assert "observation" not in _tables(connection)
    assert "schema_migrations" not in _tables(connection)


def test_applied_version_is_recorded() -> None:
    connection = sqlite3.connect(":memory:")
    apply_migrations(connection)
    row = connection.execute(
        "SELECT version, name FROM schema_migrations"
    ).fetchone()
    assert row is not None
    assert row[0] == 1
    assert row[1] == "initial"
