from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from janus.persona.evolution import (
    EvolutionScenario,
    evolve,
    split_scenarios,
)


def _scenarios(count: int = 40) -> list[EvolutionScenario]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for index in range(count):
        trend = 0.08 if index % 2 == 0 else -0.08
        rows.append(
            EvolutionScenario(
                id=f"s{index}",
                as_of=start + timedelta(days=index),
                resolved_at=start + timedelta(days=index + 30),
                outcome=1.0 if trend > 0 else 0.0,
                features={
                    "rsi_14": 65.0 if trend > 0 else 35.0,
                    "return_21d": trend,
                    "breadth": 0.65 if trend > 0 else 0.35,
                },
            )
        )
    return rows


def test_split_is_time_ordered_and_disjoint() -> None:
    train, validation = split_scenarios(_scenarios(), heldout_fraction=0.25)
    assert {scenario.id for scenario in train}.isdisjoint(
        {scenario.id for scenario in validation}
    )
    assert max(scenario.as_of for scenario in train) < min(
        scenario.as_of for scenario in validation
    )


def test_evolution_is_reproducible_with_a_seed() -> None:
    scenarios = _scenarios()
    first = evolve(scenarios, seed=11, generations=6, population_size=12)
    second = evolve(scenarios, seed=11, generations=6, population_size=12)
    assert first.to_dict() == second.to_dict()
    assert first.train_ids == second.train_ids
    assert first.validation_ids == second.validation_ids


def test_promotion_gate_keeps_baseline_when_threshold_is_high() -> None:
    result = evolve(
        _scenarios(),
        seed=5,
        generations=6,
        population_size=12,
        improvement_threshold=10.0,
    )
    assert result.promoted is False
    assert result.persona.version == "baseline"
    assert "baseline retained" in result.reason


def test_evolved_profile_is_bounded_and_versioned() -> None:
    result = evolve(
        _scenarios(),
        seed=3,
        generations=8,
        population_size=16,
        improvement_threshold=-10.0,
    )
    assert result.promoted is True
    assert result.persona.version.startswith("evolved-3-")
    assert all(0.0 <= value <= 1.0 for value in result.persona.profile.values())
    assert result.validation.brier <= 1.0


def test_invalid_inputs_are_rejected() -> None:
    with pytest.raises(ValueError, match="at least two"):
        split_scenarios(_scenarios(1))
    with pytest.raises(ValueError, match="heldout_fraction"):
        split_scenarios(_scenarios(4), heldout_fraction=0.0)
    with pytest.raises(ValueError, match="population_size"):
        evolve(_scenarios(), population_size=1)
    with pytest.raises(ValueError, match="timezone-aware"):
        EvolutionScenario(
            id="bad",
            as_of=datetime(2026, 1, 1),
            resolved_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            outcome=1.0,
            features={},
        )
