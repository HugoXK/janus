from __future__ import annotations

import json
import math
import random
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Sequence

from ..forecast.calibration import brier_score, expected_calibration_error, log_loss
from ..memory.models import Persona
from .weighting import PersonaPolicy

def _clip(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True)
class TournamentScenario:
    id: str
    entity_id: str
    as_of: datetime
    resolved_at: datetime
    outcome: float
    features: dict[str, float]
    realized_return: Optional[float] = None
    horizon: str = "1M"

    def __post_init__(self) -> None:
        _require_aware(self.as_of, "as_of")
        _require_aware(self.resolved_at, "resolved_at")
        if self.resolved_at <= self.as_of:
            raise ValueError("resolved_at must be after as_of")
        if self.outcome not in (0.0, 1.0):
            raise ValueError("outcome must be 0 or 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "entity_id": self.entity_id,
            "as_of": self.as_of.isoformat(),
            "resolved_at": self.resolved_at.isoformat(),
            "outcome": self.outcome,
            "features": dict(self.features),
            "realized_return": self.realized_return,
            "horizon": self.horizon,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TournamentScenario":
        return cls(
            id=str(payload["id"]),
            entity_id=str(payload["entity_id"]),
            as_of=datetime.fromisoformat(payload["as_of"]),
            resolved_at=datetime.fromisoformat(payload["resolved_at"]),
            outcome=float(payload["outcome"]),
            features={str(key): float(value) for key, value in payload.get("features", {}).items()},
            realized_return=(
                float(payload["realized_return"])
                if payload.get("realized_return") is not None
                else None
            ),
            horizon=str(payload.get("horizon", "1M")),
        )


@dataclass(frozen=True)
class PersonaResult:
    persona_id: str
    name: str
    n: int
    brier: float
    log_loss: float
    ece: float
    hit_rate: float
    n_returns: int
    max_drawdown: Optional[float]
    brier_ci: tuple[float, float]
    hit_rate_ci: tuple[float, float]


@dataclass(frozen=True)
class TournamentReport:
    n_scenarios: int
    scenario_ids: tuple[str, ...]
    seed: int
    bootstrap: int
    confidence: float
    personas: tuple[PersonaResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sigmoid(value: float) -> float:
    clipped = _clip(value, -50.0, 50.0)
    return 1.0 / (1.0 + math.exp(-clipped))


def persona_probability(features: dict[str, float], persona: Persona) -> float:
    """Score one evidence vector through a persona's feature weights."""

    weights = PersonaPolicy(persona.profile).feature_weights()
    rsi_value = float(features.get("rsi_14", 50.0))
    trend = _clip(float(features.get("return_21d", features.get("trend", 0.0))))
    breadth = _clip(float(features.get("breadth", 0.5)), 0.0, 1.0)
    score = (
        0.4 * ((rsi_value - 50.0) / 50.0) * weights.get("rsi_14", 1.0)
        + 0.4 * trend * weights.get("return_21d", 1.0)
        + 0.2 * (2.0 * (breadth - 0.5)) * weights.get("breadth", 1.0)
    )
    for key in ("valuation", "quality", "macro", "liquidity"):
        score += 0.1 * _clip(float(features.get(key, 0.0))) * weights.get(key, 1.0)
    return _sigmoid(score)


def max_drawdown(returns: Sequence[float]) -> float:
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for value in returns:
        equity *= 1.0 + value
        peak = max(peak, equity)
        worst = min(worst, equity / peak - 1.0)
    return abs(worst)


def _percentile(values: Sequence[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return float("nan")
    index = (len(ordered) - 1) * quantile
    lower = int(math.floor(index))
    upper = int(math.ceil(index))
    if lower == upper:
        return ordered[lower]
    weight = index - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


class PersonaTournament:
    """Compare personas on the same fixed scenario set.

    The tournament is deliberately all-personas-by-all-scenarios. It refuses an
    empty scenario set or empty persona list, so a persona cannot be published
    on a cherry-picked subset. Bootstrap intervals use a fixed seed.
    """

    def __init__(self, scenarios: Sequence[TournamentScenario]) -> None:
        if not scenarios:
            raise ValueError("at least one scenario is required")
        ids = [scenario.id for scenario in scenarios]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate scenario ids")
        self.scenarios = list(scenarios)

    def run(
        self,
        personas: Sequence[Persona],
        *,
        seed: int = 7,
        bootstrap: int = 1000,
        confidence: float = 0.95,
    ) -> TournamentReport:
        if not personas:
            raise ValueError("at least one persona is required")
        if bootstrap < 1:
            raise ValueError("bootstrap must be >= 1")
        if not 0.0 < confidence < 1.0:
            raise ValueError("confidence must be in (0, 1)")
        ids = [persona.id for persona in personas]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate persona ids")

        results = [
            self._run_persona(
                persona,
                seed=seed,
                bootstrap=bootstrap,
                confidence=confidence,
            )
            for persona in personas
        ]
        return TournamentReport(
            n_scenarios=len(self.scenarios),
            scenario_ids=tuple(scenario.id for scenario in self.scenarios),
            seed=seed,
            bootstrap=bootstrap,
            confidence=confidence,
            personas=tuple(results),
        )

    def _run_persona(
        self,
        persona: Persona,
        *,
        seed: int,
        bootstrap: int,
        confidence: float,
    ) -> PersonaResult:
        probabilities = [
            persona_probability(scenario.features, persona)
            for scenario in self.scenarios
        ]
        outcomes = [scenario.outcome for scenario in self.scenarios]
        returns = [
            (1.0 if probability >= 0.5 else -1.0) * scenario.realized_return
            for probability, scenario in zip(probabilities, self.scenarios)
            if scenario.realized_return is not None
        ]
        rng = random.Random(seed)
        brier_samples: list[float] = []
        hit_samples: list[float] = []
        n = len(self.scenarios)
        for _ in range(bootstrap):
            indices = [rng.randrange(n) for _ in range(n)]
            sampled_p = [probabilities[index] for index in indices]
            sampled_y = [outcomes[index] for index in indices]
            brier_samples.append(brier_score(sampled_p, sampled_y))
            hit_samples.append(
                sum(
                    1
                    for probability, outcome in zip(sampled_p, sampled_y)
                    if (probability >= 0.5) == bool(outcome)
                )
                / n
            )
        tail = (1.0 - confidence) / 2.0
        return PersonaResult(
            persona_id=persona.id,
            name=persona.name,
            n=n,
            brier=brier_score(probabilities, outcomes),
            log_loss=log_loss(probabilities, outcomes),
            ece=expected_calibration_error(probabilities, outcomes),
            hit_rate=sum(
                1
                for probability, outcome in zip(probabilities, outcomes)
                if (probability >= 0.5) == bool(outcome)
            )
            / n,
            n_returns=len(returns),
            max_drawdown=max_drawdown(returns) if returns else None,
            brier_ci=(
                _percentile(brier_samples, tail),
                _percentile(brier_samples, 1.0 - tail),
            ),
            hit_rate_ci=(
                _percentile(hit_samples, tail),
                _percentile(hit_samples, 1.0 - tail),
            ),
        )

    @classmethod
    def load(cls, path: str | Path) -> "PersonaTournament":
        payload = json.loads(Path(path).read_text())
        scenarios = [
            TournamentScenario.from_dict(item) for item in payload.get("scenarios", [])
        ]
        return cls(scenarios)

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {"scenarios": [scenario.to_dict() for scenario in self.scenarios]},
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        return target
