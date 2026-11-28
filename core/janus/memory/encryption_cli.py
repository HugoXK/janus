"""CLI surface for encryption at rest."""

from __future__ import annotations

import json
from pathlib import Path
from typing import NoReturn, Optional

import typer

from janus.config import load_settings
from janus.memory.encryption import EncryptionError, load_master_key
from janus.memory.encryption_service import migrate, retire, rotate, status
from janus.memory.store import JanusStore

keys_app = typer.Typer(help="Inspect, migrate, rotate, and retire encryption-at-rest keys.")


def _fail(exc: EncryptionError) -> NoReturn:
    typer.echo(f"error [{exc.code}]: {exc}", err=True)
    raise typer.Exit(code=1)


def _database(db: Optional[Path]) -> Path:
    return Path(db) if db is not None else Path(load_settings().database)


def _open_encrypted(db: Optional[Path]) -> JanusStore:
    try:
        return JanusStore(_database(db), master_key=load_master_key())
    except EncryptionError as exc:
        _fail(exc)


def _emit(payload: dict[str, object], as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    for key, value in payload.items():
        typer.echo(f"{key}: {value}")


@keys_app.command("init")
def keys_init(
    db: Optional[Path] = typer.Option(None, "--db", help="SQLite path"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Create the first data key for a plaintext store (needs a master key)."""

    store = _open_encrypted(db)
    try:
        key_id = store.enable_encryption()
    except EncryptionError as exc:
        _fail(exc)
    _emit({"active_key_id": key_id, "initialized": True}, as_json)


@keys_app.command("status")
def keys_status(
    db: Optional[Path] = typer.Option(None, "--db", help="SQLite path"),
    blob_root: Optional[Path] = typer.Option(None, "--blob-root", help="Blob store root"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Report key ids, per-table key distribution, and pending work."""

    try:
        try:
            store = JanusStore(_database(db))
        except EncryptionError:
            store = _open_encrypted(db)
        payload = status(store, blob_root=blob_root)
    except EncryptionError as exc:
        _fail(exc)
    _emit(payload, as_json)


@keys_app.command("migrate")
def keys_migrate(
    db: Optional[Path] = typer.Option(None, "--db", help="SQLite path"),
    blob_root: Optional[Path] = typer.Option(None, "--blob-root", help="Blob store root"),
    backup: Optional[Path] = typer.Option(None, "--backup", help="Pre-migration backup path"),
    batch_size: int = typer.Option(100, "--batch-size", help="Rows per batch"),
    shred_backup: bool = typer.Option(
        False, "--shred-backup", help="Delete the plaintext backup after a successful migration"
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Encrypt legacy plaintext rows and blobs with an automatic backup."""

    store = _open_encrypted(db)
    try:
        payload = migrate(
            store,
            backup_path=backup,
            blob_root=blob_root,
            batch_size=batch_size,
            shred_backup=shred_backup,
        )
    except EncryptionError as exc:
        _fail(exc)
    _emit(payload, as_json)


@keys_app.command("rotate")
def keys_rotate(
    db: Optional[Path] = typer.Option(None, "--db", help="SQLite path"),
    blob_root: Optional[Path] = typer.Option(None, "--blob-root", help="Blob store root"),
    batch_size: int = typer.Option(100, "--batch-size", help="Rows per batch"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Generate a new key id and re-encrypt rows in resumable batches."""

    store = _open_encrypted(db)
    try:
        payload = rotate(store, batch_size=batch_size, blob_root=blob_root)
    except EncryptionError as exc:
        _fail(exc)
    _emit(payload, as_json)


@keys_app.command("retire")
def keys_retire(
    key_id: str = typer.Option(..., "--key-id", help="Retired key id to delete"),
    db: Optional[Path] = typer.Option(None, "--db", help="SQLite path"),
    blob_root: Optional[Path] = typer.Option(None, "--blob-root", help="Blob store root"),
    no_blobs: bool = typer.Option(
        False, "--no-blobs", help="Assert this store has no encrypted blobs"
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Delete a retired key once no row or blob references it."""

    store = _open_encrypted(db)
    try:
        retire(store, key_id, blob_root=blob_root, assume_no_blobs=no_blobs)
    except EncryptionError as exc:
        _fail(exc)
    _emit({"retired": key_id}, as_json)
