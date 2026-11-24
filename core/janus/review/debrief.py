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
