from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from typer.testing import CliRunner

from janus.cli import app
from janus.forecast.ledger import PredictionLedger
from janus.memory.models import Observation, ObservationKind
from janus.memory.store import JanusStore
from janus.review.report import build_research_report
from janus.thesis.tracker import ThesisTracker


def _seed(store: JanusStore) -> tuple[str, str]:
    as_of = datetime(2026, 1, 2, tzinfo=timezone.utc)
    store.insert_observation(
        Observation(
            id="news-1",
            entity_id="ACME",
            kind=ObservationKind.news,
            source="rss",
            published_at=as_of - timedelta(days=1),
            value={"title": "ACME wins"},
            raw_hash="hash-1",
            raw_uri="https://example.com/acme",
        )
    )
    store.insert_observation(
        Observation(
            id="future",
            entity_id="ACME",
            kind=ObservationKind.news,
            source="rss",
            published_at=as_of + timedelta(days=1),
            value={"title": "future"},
            raw_hash="hash-future",
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
    return thesis.id, prediction.id


def test_report_is_deterministic_and_as_of_bounded() -> None:
    store = JanusStore(":memory:")
    _, prediction_id = _seed(store)
    as_of = datetime(2026, 1, 2, tzinfo=timezone.utc)

    first = build_research_report(store, "ACME", as_of)
    second = build_research_report(store, "ACME", as_of)

    assert first.to_dict() == second.to_dict()
    assert [item["id"] for item in first.evidence] == ["news-1"]
    assert first.calibration["n"] == 1
    assert first.forecasts[0]["id"] == prediction_id
    assert len(first.snapshot_hash) == 64
    assert first.quality["errors"] == []


def test_markdown_contains_citation_and_disclaimer() -> None:
    store = JanusStore(":memory:")
    _seed(store)
    report = build_research_report(
        store, "ACME", datetime(2026, 1, 2, tzinfo=timezone.utc)
    )
    markdown = report.to_markdown()
    assert "https://example.com/acme" in markdown
    assert "ACME trend continues" in markdown
    assert "falsifiers" in markdown
    assert "not investment advice" in markdown
    assert "future" not in markdown


def test_future_row_changes_no_historical_report() -> None:
    store = JanusStore(":memory:")
    _seed(store)
    as_of = datetime(2026, 1, 2, tzinfo=timezone.utc)
    before = build_research_report(store, "ACME", as_of).to_dict()

    store.insert_observation(
        Observation(
            id="later",
            entity_id="ACME",
            kind=ObservationKind.news,
            source="rss",
            published_at=as_of + timedelta(days=2),
            value={"title": "later"},
            raw_hash="hash-later",
        )
    )
    after = build_research_report(store, "ACME", as_of).to_dict()
    assert after == before


def test_cli_report_json_and_markdown(tmp_path, monkeypatch) -> None:
    path = tmp_path / "janus.db"
    store = JanusStore(path)
    _seed(store)
    monkeypatch.setenv("JANUS_DB", str(path))
    runner = CliRunner()

    json_result = runner.invoke(
        app,
        ["report", "ACME", "--as-of", "2026-01-02T00:00:00+00:00", "--json"],
    )
    assert json_result.exit_code == 0, json_result.output
    payload = json.loads(json_result.output)
    assert payload["entity_id"] == "ACME"
    assert len(payload["snapshot_hash"]) == 64

    out = tmp_path / "report.md"
    file_result = runner.invoke(
        app,
        [
            "report",
            "ACME",
            "--as-of",
            "2026-01-02T00:00:00+00:00",
            "--out",
            str(out),
        ],
    )
    assert file_result.exit_code == 0, file_result.output
    assert "not investment advice" in out.read_text()


def test_future_theses_and_forecasts_do_not_change_a_historical_report() -> None:
    store = JanusStore(":memory:")
    _seed(store)
    as_of = datetime(2026, 1, 2, tzinfo=timezone.utc)
    before = build_research_report(store, "ACME", as_of).to_dict()

    future = datetime(2026, 1, 12, tzinfo=timezone.utc)
    thesis = ThesisTracker(store).create(
        entity_id="ACME",
        statement="Future thesis that did not exist at the as-of time",
        horizon="1M",
        as_of=future,
    )
    PredictionLedger(store).record(
        thesis_id=thesis.id,
        target="direction",
        horizon="1M",
        as_of=future,
        model_version="logit-v1",
        features_hash="features-future",
        probability=0.6,
    )

    after = build_research_report(store, "ACME", as_of).to_dict()
    assert after == before
    assert all(
        datetime.fromisoformat(item["as_of"].replace("Z", "+00:00")) <= as_of
        for item in after["theses"] + after["forecasts"]
    )


def test_markdown_escapes_table_cells_and_labels_global_calibration() -> None:
    store = JanusStore(":memory:")
    _seed(store)
    as_of = datetime(2026, 1, 2, tzinfo=timezone.utc)
    store.insert_observation(
        Observation(
            id="pipe-1",
            entity_id="ACME",
            kind=ObservationKind.news,
            source="rss|feed",
            published_at=as_of - timedelta(hours=2),
            value={"title": "pipe"},
            raw_hash="hash-pipe",
        )
    )

    markdown = build_research_report(store, "ACME", as_of).to_markdown()
    assert "rss\\|feed" in markdown
    assert "store-wide (all entities, all times)" in markdown
