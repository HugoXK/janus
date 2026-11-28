from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from typer.testing import CliRunner

from janus.cli import app
from janus.forecast.ledger import PredictionLedger
from janus.mcp.service import JanusService
from janus.memory.models import Observation, ObservationKind
from janus.memory.store import JanusStore
from janus.persona.profile import DIMENSIONS
from janus.persona.tournament import PersonaTournament, TournamentScenario
from janus.persona.weighting import build_persona
from janus.thesis.tracker import ThesisTracker

runner = CliRunner()


def _seed(path) -> str:
    store = JanusStore(path)
    as_of = datetime(2026, 1, 1, tzinfo=timezone.utc)
    persona = build_persona(
        profile={dimension: 0.5 for dimension in DIMENSIONS}, name="Base"
    )
    store.insert_persona(persona)
    thesis = ThesisTracker(store).create(
        entity_id="ACME",
        statement="trend continues",
        horizon="1M",
        as_of=as_of,
        persona_id=persona.id,
    )
    prediction = PredictionLedger(store).record(
        thesis_id=thesis.id,
        target="direction",
        horizon="1M",
        as_of=as_of,
        model_version="logit-v1",
        features_hash="abc",
        probability=0.7,
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
    return prediction.id


def test_counterfactual_cli(tmp_path, monkeypatch) -> None:
    path = tmp_path / "janus.db"
    prediction_id = _seed(path)
    monkeypatch.setenv("JANUS_DB", str(path))

    result = runner.invoke(
        app, ["counterfactual", prediction_id, "--remove", "e1", "--json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["original"]["evidence_ids"] == ["e1"]
    assert payload["delta"] < 0


def test_persona_list_and_tournament_cli(tmp_path, monkeypatch) -> None:
    path = tmp_path / "janus.db"
    _seed(path)
    monkeypatch.setenv("JANUS_DB", str(path))

    listed = runner.invoke(app, ["persona", "list", "--json"])
    assert listed.exit_code == 0, listed.output
    assert json.loads(listed.output)[0]["name"] == "Base"

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
    scenarios = tournament.save(tmp_path / "tournament.json")

    result = runner.invoke(
        app,
        ["persona", "tournament", str(scenarios), "--bootstrap", "20", "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["n_scenarios"] == 1
    assert payload["personas"][0]["name"] == "Base"


def test_counterfactual_rejects_non_finite_overrides(tmp_path, monkeypatch) -> None:
    path = tmp_path / "janus.db"
    prediction_id = _seed(path)
    monkeypatch.setenv("JANUS_DB", str(path))

    for bad in ('{"rsi_14": NaN}', '{"rsi_14": Infinity}', '{"rsi_14": "abc"}'):
        result = runner.invoke(
            app, ["counterfactual", prediction_id, "--overrides", bad, "--json"]
        )
        assert result.exit_code == 2, result.output


def test_tournament_bootstrap_cap_and_root(tmp_path) -> None:
    as_of = datetime(2026, 1, 1, tzinfo=timezone.utc)
    scenarios = PersonaTournament(
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
    ).save(tmp_path / "tournament.json")
    service = JanusService(JanusStore(":memory:"), scenarios_root=tmp_path)
    with pytest.raises(ValueError, match="bootstrap"):
        service.persona_tournament(str(scenarios), bootstrap=10001)
    outside = tmp_path.parent / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="outside the configured root"):
        service.persona_tournament(str(outside))
