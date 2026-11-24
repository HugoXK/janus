from __future__ import annotations

from datetime import datetime
from typing import Any

from ..memory.models import Outcome, Prediction
from ..memory.store import JanusStore
from .ledger import PredictionLedger


def direction_label(
    start_price: float, end_price: float, flat_threshold: float = 0.0
) -> str:
    if start_price <= 0:
        raise ValueError("start_price must be positive")
    change = (end_price - start_price) / start_price
    if change > flat_threshold:
        return "up"
    if change < -flat_threshold:
        return "down"
    return "flat"


class DirectionOutcomeResolver:
    """Resolve a P(up) forecast against a start/end price pair."""

    def __init__(self, flat_threshold: float = 0.0) -> None:
        self.flat_threshold = flat_threshold

    def resolve(
        self,
        prediction: Prediction,
        *,
        start_price: float,
        end_price: float,
        source: str,
        realized_at: datetime,
    ) -> dict[str, Any]:
        del prediction
        direction = direction_label(start_price, end_price, self.flat_threshold)
        score = 1.0 if direction == "up" else 0.0
        return {
            "realized_value": {
                "direction": direction,
                "start_price": start_price,
                "end_price": end_price,
            },
            "source": source,
            "realized_at": realized_at,
            "score": score,
        }


class SettlementService:
    """Settle a prediction through a resolver and the append-only ledger."""

    def __init__(self, store: JanusStore) -> None:
        self.store = store
        self.ledger = PredictionLedger(store)

    def settle(
        self,
        prediction_id: str,
        resolver: DirectionOutcomeResolver,
        **kwargs: Any,
    ) -> Outcome:
        prediction = self.store.get_prediction(prediction_id)
        if prediction is None:
            raise KeyError(f"unknown prediction: {prediction_id}")
        resolved = resolver.resolve(prediction, **kwargs)
        return self.ledger.settle(
            prediction_id,
            realized_value=resolved["realized_value"],
            source=resolved["source"],
            realized_at=resolved["realized_at"],
            score=resolved.get("score"),
        )
