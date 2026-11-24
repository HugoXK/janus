from __future__ import annotations

from datetime import datetime, timedelta, timezone

from janus.eval.beliefbench import BeliefBench, Scenario
from janus.mcp.service import JanusService
from janus.memory.models import Observation, ObservationKind
from janus.memory.store import JanusStore


def _service() -> JanusService:
    store = JanusStore(":memory:")
    as_of = datetime(2026, 1, 1, tzinfo=timezone.utc)
    store.insert_observation(
        Observation(
            id="news-1",
            entity_id="ACME",
            kind=ObservationKind.news,
            source="rss",
            published_at=as_of - timedelta(days=1),
            value={"headline": "ACME wins a contract"},
            raw_hash="hash-1",
        )
    )
    return JanusService(store)


def test_as_of_query_and_thesis_forecast_flow() -> None:
    service = _service()
    query = service.as_of_query("ACME", "2026-01-01T00:00:00+00:00")
    assert [row["id"] for row in query] == ["news-1"]

    thesis = service.create_thesis(
        entity_id="ACME",
        statement="ACME holds its trend.",
        horizon="1M",
        as_of="2026-01-01T00:00:00+00:00",
        falsifiers=["close below 50-day average"],
    )
    assert thesis["entity_id"] == "ACME"
    assert len(service.list_theses()) == 1

    forecast = service.create_forecast(
        thesis_id=thesis["id"],
        target="direction",
        horizon="1M",
        as_of="2026-01-01T00:00:00+00:00",
        probability=0.7,
        model_version="logit-v1",
        features_hash="features",
    )
    assert forecast["probability"] == 0.7
    assert len(service.list_forecasts(thesis["id"])) == 1

    outcome = service.settle_forecast(
        prediction_id=forecast["id"],
        start_price=100.0,
        end_price=110.0,
        realized_at="2026-02-01T00:00:00+00:00",
    )
    assert outcome["score"] == 1.0

    review = service.debrief(
        prediction_id=forecast["id"],
        features={"rsi_14": 70.0, "return_21d": 0.1, "breadth": 0.7},
        regime="risk-on",
        lessons="trend held",
    )
    assert review["prediction_id"] == forecast["id"]
    assert abs(sum(review["attribution"].values()) - 1.0) < 1e-9

    report = service.calibrate()
    assert report["n"] == 1


def test_beliefbench_tool(tmp_path) -> None:
    service = _service()
    bench = BeliefBench(
        [
            Scenario(
                id="s1",
                entity_id="ACME",
                as_of=datetime(2026, 1, 1, tzinfo=timezone.utc),
                resolved_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
                question="Did ACME rise?",
                resolution={"outcome": 1.0},
            )
        ]
    )
    path = bench.save(tmp_path / "bench.json")

    report = service.beliefbench(str(path), "always_up")

    assert report["n"] == 1
    assert report["directional_accuracy"] == 1.0
