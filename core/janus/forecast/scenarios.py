from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence, Union

from pydantic import Field, model_validator

from ..memory.models import UtcModel


class ScenarioBranch(UtcModel):
    name: str
    probability: float
    thesis: str
    assumptions: list[str] = Field(default_factory=list)
    catalysts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    falsifiers: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_branch(self) -> "ScenarioBranch":
        if not 0.0 <= self.probability <= 1.0:
            raise ValueError("branch probability must be in [0, 1]")
        if not self.falsifiers:
            raise ValueError(f"branch {self.name!r} needs at least one falsifier")
        if not self.evidence:
            raise ValueError(f"branch {self.name!r} needs at least one evidence citation")
        return self


class ScenarioTree(UtcModel):
    entity_id: str
    horizon: str
    as_of: datetime
    direction_probability: float
    volatility: float
    branches: list[ScenarioBranch]

    @model_validator(mode="after")
    def _validate_tree(self) -> "ScenarioTree":
        if not self.branches:
            raise ValueError("scenario tree needs at least one branch")
        total = sum(branch.probability for branch in self.branches)
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"scenario probabilities must sum to 1, got {total}")
        names = [branch.name for branch in self.branches]
        if len(names) != len(set(names)):
            raise ValueError("scenario branch names must be unique")
        return self


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def generate_scenario_tree(
    *,
    entity_id: str,
    horizon: str,
    as_of: Union[datetime, str],
    direction_probability: float,
    volatility: float = 0.02,
    trend: float = 0.0,
    base_weight: float = 0.2,
    evidence: Optional[Sequence[str]] = None,
) -> ScenarioTree:
    """Generate a deterministic three-branch scenario tree.

    The numeric branch mass comes from the supplied direction probability and a
    fixed base-case weight. Narratives are template text; an LLM can enrich them
    later without owning the probabilities.
    """

    stamp: datetime
    if isinstance(as_of, datetime):
        stamp = as_of
    else:
        stamp = datetime.fromisoformat(str(as_of).replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.tzinfo.utcoffset(stamp) is None:
        stamp = stamp.replace(tzinfo=timezone.utc)

    probability = _clip(float(direction_probability), 0.0, 1.0)
    sigma = max(0.0, float(volatility))
    base_weight = _clip(float(base_weight), 0.0, 0.8)
    cited = list(evidence or [])
    if not cited:
        cited = [
            f"direction_probability={probability:.3f}",
            f"volatility={sigma:.4f}",
            f"trend={float(trend):.4f}",
        ]

    down_weight = (1.0 - probability) * (1.0 - base_weight)
    up_weight = probability * (1.0 - base_weight)
    move = max(0.01, sigma * 2.0)

    branches = [
        ScenarioBranch(
            name="up",
            probability=up_weight,
            thesis=f"{entity_id} resolves higher over {horizon}.",
            assumptions=[
                f"realized volatility near {sigma:.2%}",
                f"trend score {float(trend):.2f} does not reverse",
            ],
            catalysts=["breadth improves", "positive revisions"],
            risks=["volatility expands", "breadth deteriorates"],
            falsifiers=[
                f"close falls more than {move:.2%} before {horizon} ends",
                "breadth drops below 45%",
            ],
            evidence=cited,
        ),
        ScenarioBranch(
            name="base",
            probability=base_weight,
            thesis=f"{entity_id} stays range-bound over {horizon}.",
            assumptions=[f"returns stay inside roughly +/-{move:.2%}"],
            catalysts=["no new catalyst", "macro data in line"],
            risks=["a catalyst breaks the range"],
            falsifiers=[
                f"close moves more than {move:.2%} before {horizon} ends",
            ],
            evidence=cited,
        ),
        ScenarioBranch(
            name="down",
            probability=down_weight,
            thesis=f"{entity_id} resolves lower over {horizon}.",
            assumptions=[
                f"realized volatility near {sigma:.2%}",
                f"trend score {float(trend):.2f} does not recover",
            ],
            catalysts=["breadth weakens", "negative revisions"],
            risks=["oversold bounce", "breadth thrust"],
            falsifiers=[
                f"close rises more than {move:.2%} before {horizon} ends",
                "breadth rises above 55%",
            ],
            evidence=cited,
        ),
    ]

    return ScenarioTree(
        entity_id=entity_id,
        horizon=horizon,
        as_of=stamp,
        direction_probability=probability,
        volatility=sigma,
        branches=branches,
    )
