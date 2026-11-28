"""Operational side of encryption at rest: status, rotation, migration."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from .encryption import (
    EncryptionError,
    EncryptionRequiredError,
    KeyInUseError,
    KeyMissingError,
    Sealer,
    encrypted_columns,
    field_context,
)
from .store import JanusStore

_BATCH_DEFAULT = 100


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sealer(store: JanusStore) -> Sealer:
    sealer = store.sealer
    if sealer is None:
        raise KeyMissingError(
            "this store has no data key yet; run 'janus keys init' with a master key"
        )
    return sealer


def status(store: JanusStore, *, blob_root: Optional[Path] = None) -> dict[str, Any]:
    """Report key ids, per-table key distribution, and pending work."""

    connection = store.connection
    tables = encrypted_columns()
    rows: dict[str, dict[str, int]] = {}
    plaintext_rows = 0
    for table in tables:
        distribution: dict[str, int] = {}
        for row in connection.execute(
            f"SELECT COALESCE(key_id, 'plaintext') AS kid, COUNT(*) FROM {table} GROUP BY kid"
        ).fetchall():
            distribution[str(row[0])] = int(row[1])
        rows[table] = dict(sorted(distribution.items()))
        plaintext_rows += distribution.get("plaintext", 0)

    manager = store.key_manager
    keys = (
        [{"key_id": key.key_id, "state": key.state} for key in manager.keys()]
        if manager is not None
        else []
    )
    rotation = [
        {"table": str(row[0]), "last_rowid": int(row[1])}
        for row in connection.execute(
            "SELECT target, last_rowid FROM encryption_rotation ORDER BY target"
        ).fetchall()
    ]
    payload: dict[str, Any] = {
        "initialized": store.encryption_enabled,
        "active_key_id": manager.active_key_id if manager is not None else None,
        "keys": keys,
        "rows": rows,
        "plaintext_rows": plaintext_rows,
        "rotation_in_progress": bool(rotation),
        "rotation": rotation,
    }
    if blob_root is not None:
        from janus.data.blob import EncryptedBlobStore

        payload["blobs"] = EncryptedBlobStore(blob_root, _sealer(store)).status().as_dict()
    return payload


def begin_rotation(store: JanusStore) -> str:
    """Create a new active key and progress rows, or reuse a pending rotation."""

    sealer = _sealer(store)
    connection = store.connection
    pending = connection.execute("SELECT COUNT(*) FROM encryption_rotation").fetchone()
    if pending is not None and int(pending[0]) > 0:
        return sealer.active_key_id

    plaintext = sum(
        int(
            connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE key_id IS NULL"
            ).fetchone()[0]
        )
        for table in encrypted_columns()
    )
    if plaintext:
        raise EncryptionRequiredError(
            f"{plaintext} rows are still plaintext; run 'janus keys migrate' first"
        )

    manager = store.key_manager
    assert manager is not None
    key_id = manager.start_rotation()
    for table in encrypted_columns():
        connection.execute(
            "INSERT OR REPLACE INTO encryption_rotation (target, last_rowid, updated_at) "
            "VALUES (?, 0, ?)",
            (table, _now()),
        )
    connection.commit()
    return key_id


def rotate(
    store: JanusStore,
    *,
    batch_size: int = _BATCH_DEFAULT,
    blob_root: Optional[Path] = None,
    tables: Optional[Iterable[str]] = None,
) -> dict[str, Any]:
    """Re-encrypt rows under the active key id in resumable batches.

    Progress is persisted per table, so an interrupted run continues with the
    same key id on the next call. Rows already on the active key are skipped.
    """

    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")
    sealer = _sealer(store)
    connection = store.connection
    key_id = begin_rotation(store)
    selected = list(tables) if tables is not None else list(encrypted_columns())
    unknown = set(selected) - set(encrypted_columns())
    if unknown:
        raise ValueError(f"unknown encrypted table(s): {sorted(unknown)}")

    rotated = 0
    for table in selected:
        columns = encrypted_columns()[table]
        row = connection.execute(
            "SELECT last_rowid FROM encryption_rotation WHERE target = ?", (table,)
        ).fetchone()
        last = int(row[0]) if row else 0
        while True:
            rows = connection.execute(
                f"SELECT rowid, * FROM {table} WHERE rowid > ? ORDER BY rowid LIMIT ?",
                (last, batch_size),
            ).fetchall()
            if not rows:
                break
            for record in rows:
                last = int(record["rowid"])
                if record["key_id"] == key_id:
                    continue
                updates = {
                    column: sealer.rotate(
                        record[column],
                        context=field_context(table, record["id"], column),
                    )
                    for column in columns
                }
                assignments = ", ".join(f"{column} = ?" for column in updates)
                connection.execute(
                    f"UPDATE {table} SET {assignments}, key_id = ? WHERE id = ?",
                    (*updates.values(), key_id, record["id"]),
                )
                rotated += 1
            connection.execute(
                "UPDATE encryption_rotation SET last_rowid = ?, updated_at = ? WHERE target = ?",
                (last, _now(), table),
            )
            connection.commit()
        connection.execute("DELETE FROM encryption_rotation WHERE target = ?", (table,))
        connection.commit()

    blob_report = None
    if blob_root is not None:
        from janus.data.blob import EncryptedBlobStore

        blob_report = EncryptedBlobStore(blob_root, sealer).rotate().as_dict()
    return {
        "key_id": key_id,
        "rows_rotated": rotated,
        "tables": selected,
        "blobs": blob_report,
    }


def migrate(
    store: JanusStore,
    *,
    backup_path: Optional[Path] = None,
    blob_root: Optional[Path] = None,
    batch_size: int = _BATCH_DEFAULT,
    shred_backup: bool = False,
) -> dict[str, Any]:
    """Encrypt legacy plaintext rows (and blobs) with an automatic backup.

    Re-running is a no-op. Any failure restores the pre-migration database.
    """

    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")
    if store.path == ":memory:":
        raise EncryptionError("migration needs a file-backed database to take a backup")
    sealer = _sealer(store)
    connection = store.connection
    plaintext_rows = sum(
        int(
            connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE key_id IS NULL"
            ).fetchone()[0]
        )
        for table in encrypted_columns()
    )
    plaintext_blobs = 0
    if blob_root is not None:
        from janus.data.blob import EncryptedBlobStore

        plaintext_blobs = EncryptedBlobStore(blob_root, sealer).status().plaintext
    if plaintext_rows == 0 and plaintext_blobs == 0:
        return {"rows_encrypted": 0, "blobs_migrated": 0, "backup": None}

    backup = _backup_database(store, backup_path)
    encrypted = 0
    # Overwrite freed pages as rows are rewritten, then VACUUM at the end, so
    # the live file does not keep pre-migration plaintext images. The backup is
    # plaintext by definition and stays on disk unless shred_backup is set.
    connection.execute("PRAGMA secure_delete = ON")
    try:
        for table, columns in encrypted_columns().items():
            while True:
                rows = connection.execute(
                    f"SELECT rowid, * FROM {table} WHERE key_id IS NULL ORDER BY rowid LIMIT ?",
                    (batch_size,),
                ).fetchall()
                if not rows:
                    break
                for record in rows:
                    updates = {
                        column: sealer.seal(
                            str(record[column]).encode("utf-8"),
                            context=field_context(table, record["id"], column),
                        )
                        for column in columns
                    }
                    assignments = ", ".join(f"{column} = ?" for column in updates)
                    connection.execute(
                        f"UPDATE {table} SET {assignments}, key_id = ? WHERE id = ?",
                        (*updates.values(), sealer.active_key_id, record["id"]),
                    )
                    encrypted += 1
                connection.commit()
    except BaseException:
        _restore_database(store, backup)
        raise

    blobs = 0
    if blob_root is not None:
        from janus.data.blob import EncryptedBlobStore

        blobs = EncryptedBlobStore(blob_root, sealer).migrate_plaintext()
    connection.execute("VACUUM")
    connection.commit()
    mode = connection.execute("PRAGMA journal_mode").fetchone()
    if mode is not None and str(mode[0]).lower() == "wal":
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    if shred_backup:
        backup.unlink()
    return {
        "rows_encrypted": encrypted,
        "blobs_migrated": blobs,
        "backup": None if shred_backup else str(backup),
    }


def retire(
    store: JanusStore,
    key_id: str,
    *,
    blob_root: Optional[Path] = None,
    assume_no_blobs: bool = False,
) -> None:
    """Delete a retired key only when no encrypted row or blob references it."""

    connection = store.connection
    usage = sum(
        int(
            connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE key_id = ?", (key_id,)
            ).fetchone()[0]
        )
        for table in encrypted_columns()
    )
    if usage:
        raise KeyInUseError(
            f"key {key_id!r} is still used by {usage} rows; rotate them first"
        )
    blob_usage = 0
    if blob_root is not None:
        from janus.data.blob import EncryptedBlobStore

        blob_usage = EncryptedBlobStore(blob_root, _sealer(store)).status().by_key_id.get(
            key_id, 0
        )
    elif not assume_no_blobs:
        raise KeyInUseError(
            f"cannot prove key {key_id!r} is unused by blobs; pass blob_root or "
            "assume_no_blobs=True"
        )
    if blob_usage:
        raise KeyInUseError(
            f"key {key_id!r} is still used by {blob_usage} blobs; rotate them first"
        )
    manager = store.key_manager
    if manager is None:
        raise KeyMissingError("this store has no data keys")
    manager.retire(key_id)


def _backup_database(store: JanusStore, backup_path: Optional[Path]) -> Path:
    if backup_path is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = Path(f"{store.path}.pre-encryption-{stamp}.bak")
    backup = Path(backup_path)
    if backup.exists():
        raise EncryptionError(f"refusing to overwrite existing backup {backup}")
    backup.parent.mkdir(parents=True, exist_ok=True)
    destination = sqlite3.connect(str(backup))
    try:
        store._raw_connection.backup(destination)
    finally:
        destination.close()
    if os.name == "posix":
        os.chmod(backup, 0o600)
    return backup


def _restore_database(store: JanusStore, backup: Path) -> None:
    source = sqlite3.connect(str(backup))
    try:
        source.backup(store._raw_connection)
    finally:
        source.close()
