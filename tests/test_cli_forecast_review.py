from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from typer.testing import CliRunner

from janus.cli import app
from janus.forecast.ledger import PredictionLedger
from janus.memory.store import JanusStore
from janus.thesis.tracker import ThesisTracker

runner = CliRunner()


def _seed(path) -> tuple[str, str]:
    store = JanusStore(path)
    as_of = datetime(2026, 1, 1, tzinfo=timezone.utc)
    thesis = ThesisTracker(store).create(
        entity_id="ACME",
        statement="ACME trend continues",
        horizon="1M",
        as_of=as_of,
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
    return thesis.id, prediction.id


def test_forecast_list_and_create_json(tmp_path, monkeypatch) -> None:
    path = tmp_path / "janus.db"
    thesis_id, _ = _seed(path)
    monkeypatch.setenv("JANUS_DB", str(path))

    listed = runner.invoke(app, ["forecast", "list", "--json"])
    assert listed.exit_code == 0, listed.output
    assert len(json.loads(listed.output)) == 1

    created = runner.invoke(
        app,
        [
            "forecast",
            "create",
            "--thesis-id",
            thesis_id,
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


def test_review_debrief_and_calibration_json(tmp_path, monkeypatch) -> None:
    path = tmp_path / "janus.db"
    _, prediction_id = _seed(path)
    monkeypatch.setenv("JANUS_DB", str(path))

    debrief = runner.invoke(
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
    assert debrief.exit_code == 0, debrief.output
    payload = json.loads(debrief.output)
    assert payload["prediction_id"] == prediction_id
    assert sum(payload["attribution"].values()) == pytest.approx(1.0)

    calibration = runner.invoke(app, ["review", "calibration", "--json"])
    assert calibration.exit_code == 0, calibration.output
    assert json.loads(calibration.output)["n"] == 1


def test_forecast_settle_json(tmp_path, monkeypatch) -> None:
    path = tmp_path / "janus.db"
    thesis_id, _ = _seed(path)
    store = JanusStore(path)
    prediction = PredictionLedger(store).record(
        thesis_id=thesis_id,
        target="direction",
        horizon="1M",
        as_of=datetime(2026, 1, 1, tzinfo=timezone.utc),
        model_version="test-v1",
        features_hash="abc",
        probability=0.6,
    )
    monkeypatch.setenv("JANUS_DB", str(path))

    result = runner.invoke(
        app,
        [
            "forecast",
            "settle",
            prediction.id,
            "--start-price",
            "100",
            "--end-price",
            "110",
            "--realized-at",
            "2026-02-01T00:00:00+00:00",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["score"] == 1.0


def _strict_loads(text: str):
    def reject(value: str):
        raise ValueError(f"non-finite token: {value}")

    return json.loads(text, parse_constant=reject)


def test_forecast_rejects_non_finite_quantiles(tmp_path, monkeypatch) -> None:
    path = tmp_path / "janus.db"
    thesis_id, _ = _seed(path)
    monkeypatch.setenv("JANUS_DB", str(path))
    base = [
        "forecast",
        "create",
        "--thesis-id",
        thesis_id,
        "--probability",
        "0.6",
        "--model-version",
        "test-v1",
        "--features-hash",
        "abc",
        "--as-of",
        "2026-01-02T00:00:00+00:00",
    ]
    for quantiles in ('{"0.5": NaN}', '{"0.9": Infinity}', '{"0.5": "nan"}', "not-json"):
        result = runner.invoke(app, [*base, "--quantiles", quantiles, "--json"])
        assert result.exit_code == 2, (quantiles, result.output)
    assert JanusStore(path).list_predictions() != []


def test_calibration_on_an_empty_store_is_strict_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JANUS_DB", str(tmp_path / "empty.db"))
    result = runner.invoke(app, ["review", "calibration", "--json"])
    assert result.exit_code == 0, result.output
    payload = _strict_loads(result.output)
    assert payload["n"] == 0
    assert payload["brier"] is None
    assert payload["ece"] is None
    assert payload["log_loss"] is None


def test_settle_rejects_non_finite_or_non_positive_prices(tmp_path, monkeypatch) -> None:
    path = tmp_path / "janus.db"
    thesis_id, _ = _seed(path)
    store = JanusStore(path)
    prediction = PredictionLedger(store).record(
        thesis_id=thesis_id,
        target="direction",
        horizon="1M",
        as_of=datetime(2026, 1, 1, tzinfo=timezone.utc),
        model_version="test-v1",
        features_hash="abc",
        probability=0.6,
    )
    before = len(store.list_outcomes())
    monkeypatch.setenv("JANUS_DB", str(path))
    for start, end in (("nan", "110"), ("100", "inf"), ("0", "110"), ("100", "-1")):
        result = runner.invoke(
            app,
            [
                "forecast",
                "settle",
                prediction.id,
                "--start-price",
                start,
                "--end-price",
                end,
                "--realized-at",
                "2026-02-01T00:00:00+00:00",
                "--json",
            ],
        )
        assert result.exit_code == 2, (start, end, result.output)
    assert len(JanusStore(path).list_outcomes()) == before


def test_debrief_rejects_non_finite_features_and_calibration(
    tmp_path, monkeypatch
) -> None:
    path = tmp_path / "janus.db"
    _, prediction_id = _seed(path)
    monkeypatch.setenv("JANUS_DB", str(path))
    bad_features = runner.invoke(
        app,
        ["review", "debrief", prediction_id, "--features", '{"rsi_14": NaN}', "--json"],
    )
    assert bad_features.exit_code == 2, bad_features.output
    bad_calibration = runner.invoke(
        app,
        [
            "review",
            "debrief",
            prediction_id,
            "--features",
            '{"rsi_14": 62}',
            "--calibration",
            "1.5",
            "--json",
        ],
    )
    assert bad_calibration.exit_code == 2, bad_calibration.output
