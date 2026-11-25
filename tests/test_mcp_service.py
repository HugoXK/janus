from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

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
    service = JanusService(JanusStore(":memory:"), scenarios_root=tmp_path)
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


def test_beliefbench_rejects_paths_outside_root(tmp_path) -> None:
    service = JanusService(
        JanusStore(":memory:"), scenarios_root=tmp_path / "scenarios"
    )

    with pytest.raises(ValueError, match="outside"):
        service.beliefbench(str(tmp_path / "other" / "bench.json"))


def test_scenario_and_quantile_tools() -> None:
    service = _service()
    tree = service.scenario_tree(
        entity_id="ACME",
        horizon="1M",
        as_of="2026-01-01T00:00:00+00:00",
        direction_probability=0.65,
        volatility=0.025,
        evidence=["contract win"],
    )
    assert sum(branch["probability"] for branch in tree["branches"]) == pytest.approx(1.0)
    assert all(branch["falsifiers"] for branch in tree["branches"])

    forecast = service.quantile_forecast(
        [-0.02, -0.01, 0.0, 0.01, 0.02], horizon=4
    )
    assert list(forecast["quantiles"]) == ["0.10", "0.50", "0.90"]
    assert forecast["width"] == pytest.approx(0.032 * 2)


def test_counterfactual_replay_tool() -> None:
    store = JanusStore(":memory:")
    as_of = datetime(2026, 1, 1, tzinfo=timezone.utc)
    service = JanusService(store)
    thesis = service.create_thesis(
        entity_id="ACME",
        statement="trend continues",
        horizon="1M",
        as_of=as_of,
    )
    forecast = service.create_forecast(
        thesis_id=thesis["id"],
        target="direction",
        horizon="1M",
        as_of=as_of,
        probability=0.7,
        model_version="logit-v1",
        features_hash="abc",
    )
    store.insert_observation(
        Observation(
            id="e1",
            entity_id="ACME",
            kind=ObservationKind.price,
            source="test",
            published_at=as_of - timedelta(days=1),
            value={"rsi_14": 70.0, "trend": 0.8, "breadth": 0.8},
            raw_hash="e1",
        )
    )

    report = service.counterfactual_replay(
        prediction_id=forecast["id"], remove_evidence=["e1"]
    )

    assert report["recorded_probability"] == 0.7
    assert report["original"]["evidence_ids"] == ["e1"]
    assert report["counterfactual"]["probability"] == pytest.approx(0.5)
    assert report["delta"] < 0


def test_persona_tournament_tool(tmp_path) -> None:
    from janus.persona.profile import DIMENSIONS
    from janus.persona.tournament import PersonaTournament, TournamentScenario
    from janus.persona.weighting import build_persona

    store = JanusStore(":memory:")
    profile = {dimension: 0.5 for dimension in DIMENSIONS}
    persona = build_persona(profile=profile, name="Base")
    store.insert_persona(persona)
    as_of = datetime(2026, 1, 1, tzinfo=timezone.utc)
    tournament = PersonaTournament(
        [
            TournamentScenario(
                id="s1",
                entity_id="ACME",
                as_of=as_of,
                resolved_at=as_of + timedelta(days=30),
                outcome=1.0,
                features={"rsi_14": 65.0, "return_21d": 0.05, "breadth": 0.7},
                realized_return=0.04,
            )
        ]
    )
    path = tournament.save(tmp_path / "tournament.json")
    service = JanusService(store, scenarios_root=tmp_path)

    report = service.persona_tournament(str(path), bootstrap=50)

    assert report["n_scenarios"] == 1
    assert report["personas"][0]["name"] == "Base"
    assert report["personas"][0]["max_drawdown"] is not None
