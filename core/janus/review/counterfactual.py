from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Optional, Sequence

from ..memory.models import Observation
from ..memory.store import JanusStore
from ..persona.weighting import Persona, PersonaPolicy


class CounterfactualLeak(ValueError):
    """Raised when a swapped-in observation was not knowable at the as-of time."""


@dataclass(frozen=True)
class ReplaySide:
    probability: float
    features: dict[str, float]
    evidence_ids: list[str]
    reasoning: str


@dataclass(frozen=True)
class CounterfactualReport:
    prediction_id: str
    entity_id: str
    as_of: str
    recorded_probability: Optional[float]
    original: ReplaySide
    counterfactual: ReplaySide
    delta: float
    removed_evidence: list[str]
    added_evidence: list[str]
    feature_overrides: dict[str, float]
    original_persona_id: Optional[str]
    counterfactual_persona_id: Optional[str]
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clip(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _sigmoid(value: float) -> float:
    clipped = max(-50.0, min(50.0, value))
    return 1.0 / (1.0 + math.exp(-clipped))


def _features_from_observations(
    observations: Sequence[Observation],
) -> dict[str, float]:
    features: dict[str, float] = {}
    for observation in sorted(
        observations, key=lambda row: (row.published_at, row.id)
    ):
        for key, value in observation.value.items():
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                features[key] = float(value)
    return dict(sorted(features.items()))


def _score(
    features: dict[str, float], persona: Optional[Persona]
) -> float:
    rsi_value = float(features.get("rsi_14", 50.0))
    trend = _clip(
        float(features.get("trend", features.get("return_21d", 0.0)))
    )
    breadth = _clip(float(features.get("breadth", 0.5)), 0.0, 1.0)
    rsi_component = 0.4 * ((rsi_value - 50.0) / 50.0)
    trend_component = 0.4 * trend
    breadth_component = 0.2 * (2.0 * (breadth - 0.5))
    if persona is not None:
        weights = PersonaPolicy(persona.profile).feature_weights()
        rsi_component *= weights.get("rsi_14", 1.0)
        trend_component *= weights.get("return_21d", 1.0)
        breadth_component *= weights.get("breadth", 1.0)
    return _sigmoid(rsi_component + trend_component + breadth_component)


def _reasoning(
    features: dict[str, float], evidence_ids: Sequence[str], persona: Optional[Persona]
) -> str:
    persona_text = persona.name if persona is not None else "no persona"
    return (
        f"rsi_14={features.get('rsi_14', 50.0):.2f}, "
        f"trend={features.get('trend', features.get('return_21d', 0.0)):.3f}, "
        f"breadth={features.get('breadth', 0.5):.3f}; "
        f"evidence={len(evidence_ids)}; persona={persona_text}"
    )


class CounterfactualReplay:
    """Replay a recorded decision with swapped evidence or persona.

    Only observations knowable at the prediction's ``as_of`` participate. The
    report keeps the recorded probability separate from the replayed baseline so
    a model-version difference is never confused with an evidence effect.
    """

    def __init__(self, store: JanusStore) -> None:
        self.store = store

    def _persona(self, persona_id: Optional[str]) -> Optional[Persona]:
        if persona_id is None:
            return None
        persona = self.store.get_persona(persona_id)
        if persona is None:
            raise KeyError(f"unknown persona: {persona_id}")
        return persona

    def replay(
        self,
        prediction_id: str,
        *,
        remove_evidence: Sequence[str] = (),
        add_observations: Sequence[Observation] = (),
        persona_id: Optional[str] = None,
        feature_overrides: Optional[dict[str, float]] = None,
    ) -> CounterfactualReport:
        prediction = self.store.get_prediction(prediction_id)
        if prediction is None:
            raise KeyError(f"unknown prediction: {prediction_id}")
        thesis = self.store.get_thesis(prediction.thesis_id)
        if thesis is None:
            raise KeyError(f"unknown thesis: {prediction.thesis_id}")

        removed = sorted({str(value) for value in remove_evidence})
        observations = self.store.query_observations_as_of(
            thesis.entity_id, prediction.as_of, mode="published"
        )
        original_by_id = {observation.id: observation for observation in observations}

        additions: dict[str, Observation] = {}
        for observation in add_observations:
            if observation.entity_id != thesis.entity_id:
                raise ValueError(
                    "swapped evidence must belong to the prediction entity"
                )
            if observation.published_at > prediction.as_of:
                raise CounterfactualLeak(
                    f"evidence {observation.id!r} was published after as_of"
                )
            if (
                observation.valid_from is not None
                and observation.valid_from > prediction.as_of
            ):
                raise CounterfactualLeak(
                    f"evidence {observation.id!r} was not valid at as_of"
                )
            if (
                observation.valid_to is not None
                and observation.valid_to <= prediction.as_of
            ):
                raise CounterfactualLeak(
                    f"evidence {observation.id!r} was expired at as_of"
                )
            additions[observation.id] = observation

        excluded = {
            observation.id for observation in observations if observation.id in removed
        }
        original_observations = list(observations)
        counterfactual_by_id = {
            key: value
            for key, value in original_by_id.items()
            if key not in excluded
        }
        counterfactual_by_id.update(additions)
        counterfactual_observations = list(counterfactual_by_id.values())

        original_features = _features_from_observations(original_observations)
        counterfactual_features = _features_from_observations(
            counterfactual_observations
        )
        overrides = {
            str(key): float(value)
            for key, value in (feature_overrides or {}).items()
        }
        counterfactual_features.update(overrides)
        counterfactual_features = dict(sorted(counterfactual_features.items()))

        original_persona = self._persona(thesis.persona_id)
        counterfactual_persona = self._persona(persona_id) if persona_id else original_persona
        original_probability = _score(original_features, original_persona)
        counterfactual_probability = _score(
            counterfactual_features, counterfactual_persona
        )
        delta = counterfactual_probability - original_probability

        original_ids = sorted(observation.id for observation in original_observations)
        counterfactual_ids = sorted(
            observation.id for observation in counterfactual_observations
        )
        added_ids = sorted(additions)
        delta_text = f"{delta:+.3f}"
        explanation_parts = [
            f"Replayed {len(original_ids)} as-of evidence item(s).",
            f"Probability moved {delta_text}.",
        ]
        if removed:
            explanation_parts.append(
                "Removed evidence: " + ", ".join(removed) + "."
            )
        if additions:
            explanation_parts.append(
                "Added evidence: " + ", ".join(sorted(additions)) + "."
            )
        if overrides:
            explanation_parts.append(
                "Overrode features: "
                + ", ".join(f"{key}={value}" for key, value in sorted(overrides.items()))
                + "."
            )
        if counterfactual_persona is not None:
            explanation_parts.append(
                f"Counterfactual persona: {counterfactual_persona.name}."
            )

        return CounterfactualReport(
            prediction_id=prediction.id,
            entity_id=thesis.entity_id,
            as_of=prediction.as_of.isoformat(),
            recorded_probability=prediction.probability,
            original=ReplaySide(
                probability=original_probability,
                features=original_features,
                evidence_ids=original_ids,
                reasoning=_reasoning(
                    original_features, original_ids, original_persona
                ),
            ),
            counterfactual=ReplaySide(
                probability=counterfactual_probability,
                features=counterfactual_features,
                evidence_ids=counterfactual_ids,
                reasoning=_reasoning(
                    counterfactual_features, counterfactual_ids, counterfactual_persona
                ),
            ),
            delta=delta,
            removed_evidence=removed,
            added_evidence=added_ids,
            feature_overrides=dict(sorted(overrides.items())),
            original_persona_id=(
                original_persona.id if original_persona is not None else None
            ),
            counterfactual_persona_id=(
                counterfactual_persona.id
                if counterfactual_persona is not None
                else None
            ),
            explanation=" ".join(explanation_parts),
        )
