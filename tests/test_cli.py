from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from typer.testing import CliRunner

from janus.cli import app
from janus.forecast.ledger import PredictionLedger
from janus.memory.models import Observation, ObservationKind
from janus.memory.store import JanusStore
from janus.thesis.tracker import ThesisTracker

runner = CliRunner()


def _seed(path) -> str:
    store = JanusStore(path)
    as_of = datetime(2026, 1, 1, tzinfo=timezone.utc)
    store.insert_observation(
        Observation(
            id="e1",
            entity_id="ACME",
            kind=ObservationKind.news,
            source="rss",
            published_at=as_of - timedelta(days=1),
            value={"title": "ACME wins", "rsi_14": 62.0},
            raw_hash="e1",
        )
    )
    thesis = ThesisTracker(store).create(
        entity_id="ACME",
        statement="ACME trend continues",
        horizon="1M",
        as_of=as_of,
        falsifiers=["close below 50-day average"],
    )
    ledger = PredictionLedger(store)
    prediction = ledger.record(
        thesis_id=thesis.id,
        target="direction",
        horizon="1M",
        as_of=as_of,
        model_version="logit-v1",
        features_hash="features",
        probability=0.7,
    )
    ledger.settle(
        prediction.id,
        realized_value={"direction": "up"},
        source="test",
        realized_at=as_of + timedelta(days=30),
        score=1.0,
    )
    return prediction.id


@pytest.fixture()
def seeded(tmp_path, monkeypatch):
    path = tmp_path / "janus.db"
    prediction_id = _seed(path)
    monkeypatch.setenv("JANUS_DB", str(path))
    return path, prediction_id


@pytest.mark.parametrize(
    "args",
    [
        ["--help"],
        ["brief", "--help"],
        ["forecast", "--help"],
        ["review", "--help"],
        ["snapshot", "--help"],
        ["persona", "--help"],
        ["share", "--help"],
    ],
)
def test_help_pages(args) -> None:
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert "Usage" in result.output


def test_asof_json(seeded) -> None:
    result = runner.invoke(
        app, ["asof", "ACME", "2026-01-02T00:00:00+00:00", "--json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert [row["id"] for row in payload] == ["e1"]


def test_brief_json(seeded) -> None:
    result = runner.invoke(app, ["brief", "ACME", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["entity_id"] == "ACME"
    assert payload["theses"][0]["entity_id"] == "ACME"
    assert payload["observations"][0]["id"] == "e1"


def test_forecast_list_and_create_json(seeded) -> None:
    listed = runner.invoke(app, ["forecast", "list", "--json"])
    assert listed.exit_code == 0, listed.output
    rows = json.loads(listed.output)
    assert len(rows) == 1

    created = runner.invoke(
        app,
        [
            "forecast",
            "create",
            "--thesis-id",
            rows[0]["thesis_id"],
            "--probability",
            "0.6",
            "--model-version",
            "test-v1",
            "--features-hash",
            "abc",
            "--as-of",
            "2026-01-02T00:00:00+00:00",
            "--quantiles",
            '{"0.1": -0.02, "0.9": 0.03}',
            "--json",
        ],
    )
    assert created.exit_code == 0, created.output
    payload = json.loads(created.output)
    assert payload["probability"] == 0.6
    assert payload["quantiles"]["0.9"] == 0.03


def test_review_debrief_and_calibration_json(seeded) -> None:
    _, prediction_id = seeded
    result = runner.invoke(
        app,
        [
            "review",
            "debrief",
            prediction_id,
            "--features",
            '{"rsi_14": 62, "return_21d": 0.04, "breadth": 0.6}',
            "--regime",
            "risk-on",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["prediction_id"] == prediction_id
    assert sum(payload["attribution"].values()) == pytest.approx(1.0)

    report = runner.invoke(app, ["review", "calibration", "--json"])
    assert report.exit_code == 0, report.output
    assert json.loads(report.output)["n"] == 1


def test_snapshot_json_and_file(seeded, tmp_path) -> None:
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


def test_persona_list_json(seeded) -> None:
    result = runner.invoke(app, ["persona", "list", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == []
