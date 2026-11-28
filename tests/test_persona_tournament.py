from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from janus.persona.profile import DIMENSIONS
from janus.persona.tournament import (
    PersonaTournament,
    TournamentScenario,
    max_drawdown,
    persona_probability,
)
from janus.persona.weighting import build_persona


def _profile(**overrides: float) -> dict[str, float]:
    profile = {dimension: 0.5 for dimension in DIMENSIONS}
    profile.update(overrides)
    return profile


def _scenarios() -> list[TournamentScenario]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [
        (1.0, 0.04, {"rsi_14": 68.0, "return_21d": 0.05, "breadth": 0.7}),
        (0.0, -0.03, {"rsi_14": 32.0, "return_21d": -0.04, "breadth": 0.35}),
        (1.0, 0.02, {"rsi_14": 58.0, "return_21d": 0.02, "breadth": 0.58}),
        (0.0, -0.01, {"rsi_14": 45.0, "return_21d": -0.01, "breadth": 0.45}),
    ]
    return [
        TournamentScenario(
            id=f"s{index}",
            entity_id="ACME",
            as_of=start,
            resolved_at=start + timedelta(days=30),
            outcome=outcome,
            features=features,
            realized_return=realized,
        )
        for index, (outcome, realized, features) in enumerate(rows)
    ]


def test_tournament_is_reproducible_and_has_intervals() -> None:
    personas = [
        build_persona(profile=_profile(contrarian=0.9), name="Trend"),
        build_persona(profile=_profile(contrarian=0.1), name="Contrarian"),
    ]
    tournament = PersonaTournament(_scenarios())
    first = tournament.run(personas, seed=11, bootstrap=200).to_dict()
    second = tournament.run(personas, seed=11, bootstrap=200).to_dict()

    assert first == second
    assert first["n_scenarios"] == 4
    assert first["scenario_ids"] == ("s0", "s1", "s2", "s3")
    for result in first["personas"]:
        assert result["n"] == 4
        assert result["brier_ci"][0] <= result["brier"] <= result["brier_ci"][1]
        assert result["hit_rate_ci"][0] <= result["hit_rate"] <= result["hit_rate_ci"][1]
        assert result["max_drawdown"] is not None


def test_persona_weights_change_probability() -> None:
    trend = build_persona(profile=_profile(contrarian=0.9), name="Trend")
    contrarian = build_persona(profile=_profile(contrarian=0.1), name="Contrarian")
    features = {"rsi_14": 70.0, "return_21d": 0.08, "breadth": 0.7}
    assert persona_probability(features, trend) > persona_probability(
        features, contrarian
    )


def test_max_drawdown() -> None:
    assert max_drawdown([0.1, -0.2, 0.05]) == pytest.approx(0.2)
    assert max_drawdown([0.01, 0.02]) == 0.0


def test_missing_returns_leave_drawdown_empty() -> None:
    scenarios = _scenarios()
    scenarios = [
        TournamentScenario(
            id=scenario.id,
            entity_id=scenario.entity_id,
            as_of=scenario.as_of,
            resolved_at=scenario.resolved_at,
            outcome=scenario.outcome,
            features=scenario.features,
        )
        for scenario in scenarios
    ]
    report = PersonaTournament(scenarios).run(
        [build_persona(profile=_profile(), name="Base")], bootstrap=10
    )
    assert report.personas[0].n_returns == 0
    assert report.personas[0].max_drawdown is None


def test_empty_inputs_and_duplicates_are_rejected() -> None:
    with pytest.raises(ValueError, match="at least one scenario"):
        PersonaTournament([])
    scenario = _scenarios()[0]
    with pytest.raises(ValueError, match="duplicate scenario"):
        PersonaTournament([scenario, scenario])
    with pytest.raises(ValueError, match="at least one persona"):
        PersonaTournament([scenario]).run([])

    persona = build_persona(profile=_profile(), name="Base")
    with pytest.raises(ValueError, match="duplicate persona"):
        PersonaTournament([scenario]).run([persona, persona])


def test_save_and_load_round_trip(tmp_path) -> None:
    tournament = PersonaTournament(_scenarios())
    path = tournament.save(tmp_path / "tournament.json")
    loaded = PersonaTournament.load(path)
    assert [scenario.id for scenario in loaded.scenarios] == ["s0", "s1", "s2", "s3"]
    assert loaded.scenarios[0].features["rsi_14"] == 68.0
