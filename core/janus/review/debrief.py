from __future__ import annotations

from typing import Optional
from uuid import uuid4

from ..memory.models import Review
from ..memory.store import JanusStore


def simple_attribution(
    *,
    technical: float = 0.0,
    fundamental: float = 0.0,
    macro: float = 0.0,
    sentiment: float = 0.0,
    luck: float = 0.0,
) -> dict[str, float]:
    """Normalize a human or model attribution into a share of the outcome."""

    raw = {
        "technical": technical,
        "fundamental": fundamental,
        "macro": macro,
        "sentiment": sentiment,
        "luck": luck,
    }
    total = sum(abs(value) for value in raw.values())
    if total == 0.0:
        return {key: 0.0 for key in raw}
    return {key: value / total for key, value in raw.items()}


def debrief(
    store: JanusStore,
    *,
    prediction_id: str,
    attribution: dict[str, float],
    calibration: Optional[float] = None,
    lessons: str = "",
) -> Review:
    review = Review(
        id=uuid4().hex,
        prediction_id=prediction_id,
        attribution=attribution,
        calibration=calibration,
        lessons=lessons,
    )
    store.insert_review(review)
    return review


class AttributionEngine:
    """A deterministic, auditable attribution baseline."""

    def attribute(
        self,
        features: dict[str, float],
        regime: Optional[str] = None,
    ) -> dict[str, float]:
        trend = features.get("trend")
        if trend is None:
            trend = features.get("return_21d", 0.0)
        technical = (
            abs(features.get("rsi_14", 50.0) - 50.0) / 50.0
            + abs(features.get("macd_hist", 0.0))
            + abs(float(trend))
        )
        fundamental = abs(features.get("valuation", 0.0)) + abs(
            features.get("quality", 0.0)
        )
        macro = abs(features.get("breadth", 0.5) - 0.5) * 2.0
        if regime in {"risk-on", "risk-off", "high-vol"}:
            macro += 0.5
        sentiment = abs(features.get("sentiment", 0.0))
        return simple_attribution(
            technical=technical,
            fundamental=fundamental,
            macro=macro,
            sentiment=sentiment,
            luck=0.05,
        )


def debrief_prediction(
    store: JanusStore,
    *,
    prediction_id: str,
    features: dict[str, float],
    regime: Optional[str] = None,
    calibration: Optional[float] = None,
    lessons: str = "",
) -> Review:
    prediction = store.get_prediction(prediction_id)
    if prediction is None:
        raise KeyError(f"unknown prediction: {prediction_id}")
    if prediction.outcome_id is None:
        raise ValueError("prediction is not settled")
    if store.get_outcome(prediction.outcome_id) is None:
        raise ValueError("outcome is missing")
    attribution = AttributionEngine().attribute(features, regime)
    return debrief(
        store,
        prediction_id=prediction_id,
        attribution=attribution,
        calibration=calibration,
        lessons=lessons,
    )
