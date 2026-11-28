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


def _noise_scenarios(count: int = 40) -> list[EvolutionScenario]:
    """Outcomes alternate but the features carry no signal at all."""

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        EvolutionScenario(
            id=f"n{index}",
            as_of=start + timedelta(days=index),
            resolved_at=start + timedelta(days=index + 30),
            outcome=1.0 if index % 2 == 0 else 0.0,
            features={"rsi_14": 50.0, "return_21d": 0.0, "breadth": 0.5},
        )
        for index in range(count)
    ]


def test_pure_noise_is_not_promoted_at_defaults() -> None:
    scenarios = _noise_scenarios()
    for seed in range(1, 6):
        result = evolve(scenarios, seed=seed, generations=10, population_size=16)
        assert result.promoted is False, (seed, result.reason)
        assert result.persona.version == "baseline"
        assert "baseline retained" in result.reason


def test_strong_signal_is_promoted_at_defaults() -> None:
    result = evolve(_scenarios(), seed=5)
    assert result.promoted is True, result.reason
    assert result.persona.version.startswith("evolved-5-")


def test_small_heldout_set_is_never_promoted() -> None:
    result = evolve(
        _scenarios(8),
        seed=3,
        generations=6,
        population_size=12,
        improvement_threshold=-10.0,
    )
    assert result.promoted is False
    assert result.persona.version == "baseline"
    assert "minimum 5" in result.reason


def test_validation_ids_are_the_latest_scenarios() -> None:
    scenarios = _scenarios()
    result = evolve(scenarios, seed=11, generations=4, population_size=10)
    ordered = sorted(scenarios, key=lambda scenario: (scenario.as_of, scenario.id))
    assert result.validation_ids == tuple(scenario.id for scenario in ordered[-10:])
    assert set(result.train_ids).isdisjoint(result.validation_ids)
