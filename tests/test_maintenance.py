from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from typer.testing import CliRunner

from janus.cli import app
from janus.memory.maintenance import backup, integrity_check, stats, vacuum
from janus.memory.models import Observation, ObservationKind
from janus.memory.store import JanusStore
from janus.thesis.tracker import ThesisTracker

runner = CliRunner()


def _seed(path) -> JanusStore:
    store = JanusStore(path)
    as_of = datetime(2026, 1, 1, tzinfo=timezone.utc)
    store.insert_observation(
        Observation(
            id="news",
            entity_id="ACME",
            kind=ObservationKind.news,
            source="rss",
            published_at=as_of,
            value={"title": "story"},
            raw_hash="hash",
        )
    )
    ThesisTracker(store).create(
        entity_id="ACME", statement="x", horizon="1M", as_of=as_of
    )
    return store


def test_integrity_and_stats(tmp_path) -> None:
    store = _seed(tmp_path / "janus.db")
    assert integrity_check(store).ok is True
    payload = stats(store)
    assert payload["rows"]["observation"] == 1
    assert payload["rows"]["thesis"] == 1
    assert payload["total_rows"] == 2
    assert payload["bytes"] > 0
    vacuum(store)


def test_backup_is_a_complete_store(tmp_path) -> None:
    store = _seed(tmp_path / "janus.db")
    target = backup(store, tmp_path / "backup.db")
    restored = JanusStore(target)
    assert integrity_check(restored).ok is True
    assert stats(restored)["total_rows"] == 2
    assert restored.get_observation("news") is not None


def test_db_cli_check_stats_backup(tmp_path, monkeypatch) -> None:
    path = tmp_path / "janus.db"
    _seed(path)
    monkeypatch.setenv("JANUS_DB", str(path))

    checked = runner.invoke(app, ["db", "check", "--json"])
    assert checked.exit_code == 0, checked.output
    assert json.loads(checked.output)["ok"] is True

    counted = runner.invoke(app, ["db", "stats", "--json"])
    assert counted.exit_code == 0, counted.output
    assert json.loads(counted.output)["total_rows"] == 2

    target = tmp_path / "backup.db"
    saved = runner.invoke(app, ["db", "backup", str(target)])
    assert saved.exit_code == 0, saved.output
    assert target.exists()


def test_integrity_check_reports_a_corrupt_database(tmp_path) -> None:
    path = tmp_path / "janus.db"
    _seed(path).close()
    # truncate the file so SQLite cannot read the schema/pages back
    data = path.read_bytes()
    path.write_bytes(data[: len(data) // 2])

    report = integrity_check(str(path))
    assert report.ok is False
    assert report.integrity  # a reason is reported, not an exception

    checked = runner.invoke(app, ["db", "check", "--db", str(path), "--json"])
    assert checked.exit_code == 1
    payload = json.loads(checked.output)
    assert payload["ok"] is False
    assert payload["integrity"]


def test_backup_refuses_to_overwrite_without_force(tmp_path) -> None:
    store = _seed(tmp_path / "janus.db")
    target = tmp_path / "backup.db"
    target.write_text("not a database")

    try:
        backup(store, target)
    except FileExistsError as exc:
        assert "already exists" in str(exc)
    else:  # pragma: no cover - the assertion below is the contract
        raise AssertionError("backup overwrote an existing file without force")

    backup(store, target, force=True)
    restored = JanusStore(target)
    assert integrity_check(restored).ok is True


def test_stats_derives_tables_from_the_schema(tmp_path) -> None:
    store = _seed(tmp_path / "janus.db")
    payload = stats(store)
    assert "audit_entry" in payload["rows"]
    assert payload["rows"]["audit_entry"] == 0


def test_vacuum_rejects_an_open_transaction(tmp_path) -> None:
    store = _seed(tmp_path / "janus.db")
    store.connection.execute("BEGIN")
    try:
        with pytest.raises(RuntimeError, match="open transaction"):
            vacuum(store)
    finally:
        store.connection.rollback()


def test_db_cli_vacuum(tmp_path, monkeypatch) -> None:
    path = tmp_path / "janus.db"
    _seed(path).close()
    monkeypatch.setenv("JANUS_DB", str(path))
    result = runner.invoke(app, ["db", "vacuum"])
    assert result.exit_code == 0, result.output
    assert "vacuum complete" in result.output
