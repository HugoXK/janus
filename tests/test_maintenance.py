from __future__ import annotations

import json
from datetime import datetime, timezone

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
