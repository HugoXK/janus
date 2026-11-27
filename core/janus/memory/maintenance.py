from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .store import JanusStore

TABLES = (
    "observation",
    "thesis",
    "prediction",
    "outcome",
    "persona",
    "review",
    "entity",
    "entity_alias",
    "feature_value",
    "ingestion_run",
    "ingestion_dead_letter",
)


@dataclass(frozen=True)
class IntegrityReport:
    ok: bool
    integrity: tuple[str, ...]
    foreign_key_errors: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def integrity_check(store: JanusStore) -> IntegrityReport:
    integrity = [
        str(row[0])
        for row in store.connection.execute("PRAGMA integrity_check").fetchall()
    ]
    foreign_key_errors = [
        dict(row)
        for row in store.connection.execute("PRAGMA foreign_key_check").fetchall()
    ]
    return IntegrityReport(
        ok=integrity == ["ok"] and not foreign_key_errors,
        integrity=tuple(integrity),
        foreign_key_errors=tuple(foreign_key_errors),
    )


def backup(store: JanusStore, target: Path) -> Path:
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    destination = sqlite3.connect(path)
    try:
        store.connection.backup(destination)
        destination.commit()
    finally:
        destination.close()
    return path


def vacuum(store: JanusStore) -> None:
    store.connection.execute("VACUUM")
    store.connection.commit()


def stats(store: JanusStore) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for table in TABLES:
        counts[table] = int(
            store.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        )
    path = Path(store.path)
    return {
        "path": store.path,
        "exists": path.exists(),
        "bytes": path.stat().st_size if path.exists() else 0,
        "schema_version": store.schema_version,
        "rows": counts,
        "total_rows": sum(counts.values()),
    }
