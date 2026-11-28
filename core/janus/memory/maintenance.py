from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Union

from .store import JanusStore

StoreOrPath = Union[JanusStore, str, Path]


@dataclass(frozen=True)
class IntegrityReport:
    ok: bool
    integrity: tuple[str, ...]
    foreign_key_errors: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _store_path(target: StoreOrPath) -> str:
    if isinstance(target, JanusStore):
        return target.path
    return str(target)


def _read_only_connection(path: str) -> sqlite3.Connection:
    """Open an existing database read-only, without applying migrations."""

    uri = f"{Path(path).resolve().as_uri()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def integrity_check(target: StoreOrPath) -> IntegrityReport:
    """Run SQLite integrity and foreign-key checks without mutating anything.

    A corrupt file must produce ``ok=False``, not an exception: the check opens
    a read-only raw connection and never applies migrations, because migrating a
    damaged database is exactly the state this command exists to diagnose.
    """

    path = _store_path(target)
    if path == ":memory:":
        if not isinstance(target, JanusStore):
            return IntegrityReport(
                ok=False,
                integrity=("in-memory database requires a JanusStore",),
                foreign_key_errors=(),
            )
        with target.locked():
            return _run_pragmas(target.connection)

    try:
        connection = _read_only_connection(path)
    except sqlite3.Error as exc:
        return IntegrityReport(
            ok=False,
            integrity=(f"cannot open database: {exc}",),
            foreign_key_errors=(),
        )
    try:
        return _run_pragmas(connection)
    except sqlite3.DatabaseError as exc:
        return IntegrityReport(
            ok=False,
            integrity=(str(exc),),
            foreign_key_errors=(),
        )
    finally:
        connection.close()


def _run_pragmas(connection: Any) -> IntegrityReport:
    integrity = [
        str(row[0])
        for row in connection.execute("PRAGMA integrity_check").fetchall()
    ]
    foreign_key_errors = [
        dict(row)
        for row in connection.execute("PRAGMA foreign_key_check").fetchall()
    ]
    return IntegrityReport(
        ok=integrity == ["ok"] and not foreign_key_errors,
        integrity=tuple(integrity),
        foreign_key_errors=tuple(foreign_key_errors),
    )


def backup(store: JanusStore, target: Path, *, force: bool = False) -> Path:
    """Write a consistent SQLite backup, refusing to overwrite by default."""

    path = Path(target)
    if path.exists() and path.stat().st_size > 0 and not force:
        raise FileExistsError(
            f"backup target already exists: {path} (pass force=True to overwrite)"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    destination = sqlite3.connect(path)
    try:
        with store.locked():
            store.connection.backup(destination)
            destination.commit()
    finally:
        destination.close()
    return path


def vacuum(store: JanusStore) -> None:
    """Reclaim space. VACUUM cannot run inside an open transaction."""

    with store.locked():
        if store.connection.in_transaction:
            raise RuntimeError("VACUUM requires no open transaction")
        store.connection.execute("VACUUM")
        store.connection.commit()


def _table_names(connection: Any) -> tuple[str, ...]:
    rows = connection.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
          AND name != 'schema_migrations'
        ORDER BY name
        """
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


def stats(store: JanusStore) -> dict[str, Any]:
    with store.locked():
        counts = {
            table: int(
                store.connection.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
            )
            for table in _table_names(store.connection)
        }
    path = Path(store.path)
    return {
        "path": store.path,
        "exists": path.exists(),
        "bytes": path.stat().st_size if path.exists() else 0,
        "schema_version": store.schema_version,
        "rows": counts,
        "total_rows": sum(counts.values()),
    }
