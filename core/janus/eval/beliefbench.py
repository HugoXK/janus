from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from ..forecast.calibration import brier_score, expected_calibration_error


@dataclass(frozen=True)
class Scenario:
    """A historical as-of question with a later resolution."""

    id: str
    entity_id: str
    as_of: datetime
    question: str
    resolution: dict[str, Any]
    horizon: str = "1M"
    tags: tuple[str, ...] = ()


@dataclass
class BeliefBench:
    """Lookahead-free evaluation harness.

    V1 keeps the harness small: add scenarios, run them with an as-of store, and
    score both evidence quality and calibration. The full runner lands with the
    forecast engine.
    """

    scenarios: list[Scenario] = field(default_factory=list)

    def add(self, scenario: Scenario) -> None:
        if any(existing.id == scenario.id for existing in self.scenarios):
            raise ValueError(f"duplicate scenario id: {scenario.id}")
        self.scenarios.append(scenario)

    def __len__(self) -> int:
        return len(self.scenarios)

    def calibration_summary(
        self,
        probabilities: list[float],
        outcomes: list[float],
        *,
        bins: int = 10,
        subset: Optional[list[str]] = None,
    ) -> dict[str, float]:
        """A convenience wrapper used by notebooks and the CLI."""

        if subset is not None:
            selected = [(p, o) for s, p, o in zip(self.scenarios, probabilities, outcomes) if s.id in subset]
            probabilities = [p for p, _ in selected]
            outcomes = [o for _, o in selected]
        return {
            "brier": brier_score(probabilities, outcomes),
            "ece": expected_calibration_error(probabilities, outcomes, bins=bins),
            "n": float(len(probabilities)),
        }
