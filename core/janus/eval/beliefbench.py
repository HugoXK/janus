from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from ..forecast.calibration import (
    brier_score,
    expected_calibration_error,
    log_loss,
)


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True)
class Scenario:
    """A historical as-of question with a later resolution."""

    id: str
    entity_id: str
    as_of: datetime
    resolved_at: datetime
    question: str
    resolution: dict[str, Any]
    horizon: str = "1M"
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_aware(self.as_of, "as_of")
        _require_aware(self.resolved_at, "resolved_at")
        if self.resolved_at <= self.as_of:
            raise ValueError("resolved_at must be after as_of")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "entity_id": self.entity_id,
            "as_of": self.as_of.isoformat(),
            "resolved_at": self.resolved_at.isoformat(),
            "question": self.question,
            "resolution": self.resolution,
            "horizon": self.horizon,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Scenario":
        return cls(
            id=payload["id"],
            entity_id=payload["entity_id"],
            as_of=datetime.fromisoformat(payload["as_of"]),
            resolved_at=datetime.fromisoformat(payload["resolved_at"]),
            question=payload["question"],
            resolution=dict(payload.get("resolution", {})),
            horizon=payload.get("horizon", "1M"),
            tags=tuple(payload.get("tags", ())),
        )


@dataclass(frozen=True)
class ScenarioResult:
    scenario_id: str
    probability: float
    outcome: float
    evidence: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BenchmarkReport:
    n: int
    brier: float
    log_loss: float
    ece: float
    directional_accuracy: float
    citation_coverage: float
    by_horizon: dict[str, dict[str, float]]
    by_tag: dict[str, dict[str, float]]


@dataclass
class BeliefBench:
    """Lookahead-free evaluation harness.

    The runner receives a ``Scenario`` and must answer using only the evidence
    available at ``scenario.as_of``. The harness validates the probabilities,
    outcomes, and resolution times; it does not inspect the runner's internals.
    """

    scenarios: list[Scenario] = field(default_factory=list)

    def add(self, scenario: Scenario) -> None:
        if any(existing.id == scenario.id for existing in self.scenarios):
            raise ValueError(f"duplicate scenario id: {scenario.id}")
        self.scenarios.append(scenario)

    def __len__(self) -> int:
        return len(self.scenarios)

    def run(self, runner: Callable[[Scenario], ScenarioResult]) -> BenchmarkReport:
        if not self.scenarios:
            raise ValueError("no scenarios")
        results: list[ScenarioResult] = []
        for scenario in self.scenarios:
            result = runner(scenario)
            if result.scenario_id != scenario.id:
                raise ValueError(
                    f"runner returned {result.scenario_id!r} for {scenario.id!r}"
                )
            if not 0.0 <= result.probability <= 1.0:
                raise ValueError(f"probability out of range for {scenario.id}")
            if result.outcome not in (0.0, 1.0):
                raise ValueError(f"outcome must be 0 or 1 for {scenario.id}")
            results.append(result)

        probabilities = [result.probability for result in results]
        outcomes = [result.outcome for result in results]
        return BenchmarkReport(
            n=len(results),
            brier=brier_score(probabilities, outcomes),
            log_loss=log_loss(probabilities, outcomes),
            ece=expected_calibration_error(probabilities, outcomes),
            directional_accuracy=sum(
                1
                for result in results
                if (result.probability >= 0.5) == bool(result.outcome)
            )
            / len(results),
            citation_coverage=sum(1 for result in results if result.evidence)
            / len(results),
            by_horizon=self._slice(
                results, {scenario.id: scenario.horizon for scenario in self.scenarios}
            ),
            by_tag=self._slice_by_tag(
                results, {scenario.id: scenario.tags for scenario in self.scenarios}
            ),
        )

    @staticmethod
    def _metrics(results: Sequence[ScenarioResult]) -> dict[str, float]:
        probabilities = [result.probability for result in results]
        outcomes = [result.outcome for result in results]
        return {
            "n": float(len(results)),
            "brier": brier_score(probabilities, outcomes),
            "ece": expected_calibration_error(probabilities, outcomes),
            "directional_accuracy": sum(
                1
                for result in results
                if (result.probability >= 0.5) == bool(result.outcome)
            )
            / len(results),
            "citation_coverage": sum(1 for result in results if result.evidence)
            / len(results),
        }

    @classmethod
    def _slice(
        cls,
        results: Sequence[ScenarioResult],
        labels: dict[str, str],
    ) -> dict[str, dict[str, float]]:
        groups: dict[str, list[ScenarioResult]] = {}
        for result in results:
            groups.setdefault(labels.get(result.scenario_id, "unknown"), []).append(result)
        return {name: cls._metrics(group) for name, group in groups.items()}

    @classmethod
    def _slice_by_tag(
        cls,
        results: Sequence[ScenarioResult],
        tags: dict[str, tuple[str, ...]],
    ) -> dict[str, dict[str, float]]:
        groups: dict[str, list[ScenarioResult]] = {}
        for result in results:
            for tag in tags.get(result.scenario_id, ("untagged",)):
                groups.setdefault(tag, []).append(result)
        return {name: cls._metrics(group) for name, group in groups.items()}

    @classmethod
    def load(cls, path: str | Path) -> "BeliefBench":
        payload = json.loads(Path(path).read_text())
        bench = cls()
        for item in payload.get("scenarios", []):
            bench.add(Scenario.from_dict(item))
        return bench

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {"scenarios": [scenario.to_dict() for scenario in self.scenarios]},
                indent=2,
                sort_keys=True,
                default=str,
            )
            + "\n"
        )
        return target

    def calibration_summary(
        self,
        probabilities: list[float],
        outcomes: list[float],
        *,
        bins: int = 10,
        subset: Optional[list[str]] = None,
    ) -> dict[str, float]:
        if subset is not None:
            selected = [
                (probability, outcome)
                for scenario, probability, outcome in zip(
                    self.scenarios, probabilities, outcomes
                )
                if scenario.id in subset
            ]
            probabilities = [probability for probability, _ in selected]
            outcomes = [outcome for _, outcome in selected]
        return {
            "brier": brier_score(probabilities, outcomes),
            "ece": expected_calibration_error(probabilities, outcomes, bins=bins),
            "n": float(len(probabilities)),
        }
