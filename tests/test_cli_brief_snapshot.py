from __future__ import annotations

import json
from datetime import datetime, timezone

from typer.testing import CliRunner

from janus.cli import app
from janus.memory.models import Observation, ObservationKind
from janus.memory.store import JanusStore
from janus.thesis.tracker import ThesisTracker

runner = CliRunner()


def _seed(path) -> None:
    store = JanusStore(path)
    as_of = datetime(2026, 1, 1, tzinfo=timezone.utc)
    store.insert_observation(
        Observation(
            id="news",
            entity_id="ACME",
            kind=ObservationKind.news,
            source="rss",
            published_at=as_of,
            value={"title": "ACME wins"},
            raw_hash="hash",
        )
    )
    ThesisTracker(store).create(
        entity_id="ACME", statement="trend", horizon="1M", as_of=as_of
    )


def test_brief_json(tmp_path, monkeypatch) -> None:
    path = tmp_path / "janus.db"
    _seed(path)
    monkeypatch.setenv("JANUS_DB", str(path))

    result = runner.invoke(app, ["brief", "ACME", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["entity_id"] == "ACME"
    assert payload["observations"][0]["id"] == "news"
    assert payload["theses"][0]["entity_id"] == "ACME"


def test_snapshot_json_and_file(tmp_path, monkeypatch) -> None:
    path = tmp_path / "janus.db"
    _seed(path)
    monkeypatch.setenv("JANUS_DB", str(path))

    result = runner.invoke(
        app,
        ["snapshot", "ACME", "--as-of", "2026-01-02T00:00:00+00:00", "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["count"] == 1
    assert len(payload["snapshot_hash"]) == 64

    out = tmp_path / "snapshot.json"
    written = runner.invoke(
        app,
        [
            "snapshot",
            "ACME",
            "--as-of",
            "2026-01-02T00:00:00+00:00",
            "--out",
            str(out),
        ],
    )
    assert written.exit_code == 0, written.output
    assert json.loads(out.read_text())["snapshot_hash"] == payload["snapshot_hash"]
