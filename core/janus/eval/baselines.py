from __future__ import annotations

import random
from dataclasses import dataclass, field

from .beliefbench import BenchmarkReport, BeliefBench, Scenario, ScenarioResult


def _outcome(scenario: Scenario) -> float:
    value = scenario.resolution.get("outcome")
    if value not in (0, 1):
        raise ValueError(f"scenario {scenario.id} has no binary resolution outcome")
    return float(value)


@dataclass
class ConstantBaseline:
    probability: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.probability <= 1.0:
            raise ValueError("probability must be in [0, 1]")

    def __call__(self, scenario: Scenario) -> ScenarioResult:
        return ScenarioResult(
            scenario_id=scenario.id,
            probability=self.probability,
            outcome=_outcome(scenario),
            evidence=(f"baseline:constant:{self.probability}",),
            metadata={"baseline": "constant"},
        )


@dataclass
class RandomBaseline:
    seed: int = 7
    _rng: random.Random = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    def __call__(self, scenario: Scenario) -> ScenarioResult:
        return ScenarioResult(
            scenario_id=scenario.id,
            probability=self._rng.random(),
            outcome=_outcome(scenario),
            evidence=("baseline:random",),
            metadata={"baseline": "random", "seed": self.seed},
        )


def run_baselines(bench: BeliefBench) -> dict[str, BenchmarkReport]:
    return {
        "always_up": bench.run(ConstantBaseline(1.0)),
        "always_down": bench.run(ConstantBaseline(0.0)),
        "random": bench.run(RandomBaseline()),
    }
