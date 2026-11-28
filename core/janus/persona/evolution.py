from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Optional, Sequence

from ..forecast.calibration import brier_score
from ..memory.models import Persona
from .profile import DIMENSIONS
from .weighting import PersonaPolicy, build_persona

#: A promotion needs at least this many held-out scenarios. Below this floor a
#: Brier delta cannot be distinguished from noise, so the baseline is retained.
MIN_VALIDATION_SIZE = 5

#: Default minimum held-out Brier improvement required for promotion.
DEFAULT_IMPROVEMENT_THRESHOLD = 0.01


def _clip(value: float) -> float:
    return max(0.0, min(1.0, value))


def _sigmoid(value: float) -> float:
    value = max(-50.0, min(50.0, value))
    return 1.0 / (1.0 + math.exp(-value))


@dataclass(frozen=True)
class EvolutionScenario:
    id: str
    as_of: datetime
    resolved_at: datetime
    outcome: float
    features: dict[str, float]

    def __post_init__(self) -> None:
        for name, stamp in (("as_of", self.as_of), ("resolved_at", self.resolved_at)):
            if stamp.tzinfo is None or stamp.tzinfo.utcoffset(stamp) is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.resolved_at <= self.as_of:
            raise ValueError("resolved_at must be after as_of")
        if self.outcome not in (0.0, 1.0):
            raise ValueError("outcome must be 0 or 1")


@dataclass(frozen=True)
class Fitness:
    n: int
    brier: float
    hit_rate: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Generation:
    index: int
    best_brier: float
    mean_brier: float
    best_profile: dict[str, float]


@dataclass(frozen=True)
class EvolutionResult:
    seed: int
    generations: tuple[Generation, ...]
    train: Fitness
    validation: Fitness
    baseline_validation: Fitness
    promoted: bool
    reason: str
    persona: Persona
    train_ids: tuple[str, ...]
    validation_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "generations": [asdict(generation) for generation in self.generations],
            "train": self.train.to_dict(),
            "validation": self.validation.to_dict(),
            "baseline_validation": self.baseline_validation.to_dict(),
            "promoted": self.promoted,
            "reason": self.reason,
            "persona": self.persona.model_dump(mode="json"),
            "train_ids": list(self.train_ids),
            "validation_ids": list(self.validation_ids),
        }


def persona_probability(features: dict[str, float], profile: dict[str, float]) -> float:
    weights = PersonaPolicy(profile).feature_weights()
    rsi_value = float(features.get("rsi_14", 50.0))
    trend = _clip(float(features.get("return_21d", features.get("trend", 0.0))))
    breadth = _clip(float(features.get("breadth", 0.5)))
    score = (
        0.4 * ((rsi_value - 50.0) / 50.0) * weights.get("rsi_14", 1.0)
        + 0.4 * trend * weights.get("return_21d", 1.0)
        + 0.2 * (2.0 * (breadth - 0.5)) * weights.get("breadth", 1.0)
    )
    for key in ("valuation", "quality", "macro", "liquidity"):
        score += 0.1 * _clip(float(features.get(key, 0.0))) * weights.get(key, 1.0)
    return _sigmoid(score)


def _fitness(profile: dict[str, float], scenarios: Sequence[EvolutionScenario]) -> Fitness:
    probabilities = [persona_probability(scenario.features, profile) for scenario in scenarios]
    outcomes = [scenario.outcome for scenario in scenarios]
    hit = sum(
        1
        for probability, outcome in zip(probabilities, outcomes)
        if (probability >= 0.5) == bool(outcome)
    ) / len(scenarios)
    return Fitness(n=len(scenarios), brier=brier_score(probabilities, outcomes), hit_rate=hit)


def split_scenarios(
    scenarios: Sequence[EvolutionScenario], *, heldout_fraction: float = 0.25
) -> tuple[list[EvolutionScenario], list[EvolutionScenario]]:
    if not 0.0 < heldout_fraction < 1.0:
        raise ValueError("heldout_fraction must be in (0, 1)")
    ordered = sorted(scenarios, key=lambda scenario: (scenario.as_of, scenario.id))
    if len(ordered) < 2:
        raise ValueError("at least two scenarios are required")
    validation_size = max(1, int(round(len(ordered) * heldout_fraction)))
    validation_size = min(validation_size, len(ordered) - 1)
    return ordered[:-validation_size], ordered[-validation_size:]


def _neutral_profile() -> dict[str, float]:
    return {dimension: 0.5 for dimension in DIMENSIONS}


def _mutate(
    profile: dict[str, float], rng: random.Random, rate: float, scale: float = 0.15
) -> dict[str, float]:
    child = dict(profile)
    for dimension in DIMENSIONS:
        if rng.random() < rate:
            child[dimension] = _clip(child[dimension] + rng.uniform(-scale, scale))
    return child


def _crossover(
    left: dict[str, float], right: dict[str, float], rng: random.Random
) -> dict[str, float]:
    return {
        dimension: left[dimension] if rng.random() < 0.5 else right[dimension]
        for dimension in DIMENSIONS
    }


def evolve(
    scenarios: Sequence[EvolutionScenario],
    *,
    seed: int = 7,
    generations: int = 20,
    population_size: int = 24,
    mutation_rate: float = 0.2,
    elite_fraction: float = 0.1,
    heldout_fraction: float = 0.25,
    improvement_threshold: float = DEFAULT_IMPROVEMENT_THRESHOLD,
    base_profile: Optional[dict[str, float]] = None,
) -> EvolutionResult:
    """Deterministic evolutionary search with a held-out promotion gate.

    The search optimizes training Brier score only. A candidate is promoted only
    when the held-out set has at least :data:`MIN_VALIDATION_SIZE` scenarios and
    validation Brier improves by more than ``improvement_threshold`` (default
    :data:`DEFAULT_IMPROVEMENT_THRESHOLD`) over the neutral baseline; otherwise
    the baseline persona is returned.
    """

    if generations < 1 or population_size < 2:
        raise ValueError("generations >= 1 and population_size >= 2 are required")
    if not 0.0 < elite_fraction < 1.0:
        raise ValueError("elite_fraction must be in (0, 1)")
    train, validation = split_scenarios(scenarios, heldout_fraction=heldout_fraction)
    baseline_profile = dict(base_profile or _neutral_profile())
    for dimension in DIMENSIONS:
        baseline_profile.setdefault(dimension, 0.5)
        baseline_profile[dimension] = _clip(float(baseline_profile[dimension]))
    baseline_validation = _fitness(baseline_profile, validation)

    rng = random.Random(seed)
    population = [dict(baseline_profile)]
    while len(population) < population_size:
        population.append(_mutate(baseline_profile, rng, 1.0, scale=0.3))

    history: list[Generation] = []
    elite_count = max(1, int(round(population_size * elite_fraction)))
    for index in range(generations):
        ranked = sorted(
            population,
            key=lambda profile: (_fitness(profile, train).brier, profile["contrarian"]),
        )
        scores = [_fitness(profile, train) for profile in ranked]
        history.append(
            Generation(
                index=index,
                best_brier=scores[0].brier,
                mean_brier=sum(score.brier for score in scores) / len(scores),
                best_profile=dict(ranked[0]),
            )
        )
        elites = [dict(profile) for profile in ranked[:elite_count]]
        next_population = [dict(profile) for profile in elites]
        while len(next_population) < population_size:
            left = elites[rng.randrange(len(elites))]
            right = elites[rng.randrange(len(elites))]
            next_population.append(
                _mutate(_crossover(left, right, rng), rng, mutation_rate)
            )
        population = next_population

    best = min(population, key=lambda profile: _fitness(profile, train).brier)
    validation_fitness = _fitness(best, validation)
    improvement = baseline_validation.brier - validation_fitness.brier
    enough_validation = len(validation) >= MIN_VALIDATION_SIZE
    promoted = enough_validation and improvement > improvement_threshold
    chosen = best if promoted else baseline_profile
    persona = build_persona(profile=chosen, name="Evolved" if promoted else "Baseline")
    generation_count = len(history)
    version = f"evolved-{seed}-{generation_count}" if promoted else "baseline"
    persona_id = hashlib.sha256(
        json.dumps(
            {"profile": chosen, "seed": seed, "version": version},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:32]
    persona = persona.model_copy(
        update={
            "id": persona_id,
            "version": version,
            "created_at": train[-1].resolved_at,
        }
    )
    if promoted:
        reason = (
            f"validation Brier improved by {improvement:.4f} "
            f"(threshold {improvement_threshold:.4f})"
        )
    elif not enough_validation:
        reason = (
            f"held-out set has {len(validation)} scenarios "
            f"(minimum {MIN_VALIDATION_SIZE}); baseline retained"
        )
    else:
        reason = (
            f"held-out Brier did not improve by {improvement_threshold:.4f}; "
            "baseline retained"
        )
    return EvolutionResult(
        seed=seed,
        generations=tuple(history),
        train=_fitness(chosen, train),
        validation=_fitness(chosen, validation) if promoted else baseline_validation,
        baseline_validation=baseline_validation,
        promoted=promoted,
        reason=reason,
        persona=persona,
        train_ids=tuple(scenario.id for scenario in train),
        validation_ids=tuple(scenario.id for scenario in validation),
    )
