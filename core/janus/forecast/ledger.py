from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from ..memory.models import Outcome, Prediction, utcnow
from ..memory.store import JanusStore


class PredictionLedger:
    """Append-only prediction ledger.

    The whole point is that a forecast is recorded *before* the outcome is
    known. There is no update path for the forecast itself; only an outcome can
    be attached later.
    """

    def __init__(self, store: JanusStore) -> None:
        self.store = store

    def record(
        self,
        *,
        thesis_id: str,
        target: str,
        horizon: str,
        as_of: datetime,
        model_version: str,
        features_hash: str,
        probability: Optional[float] = None,
        quantiles: Optional[dict[str, float]] = None,
    ) -> Prediction:
        if probability is not None and not 0.0 <= probability <= 1.0:
            raise ValueError("probability must be in [0, 1]")
        if as_of > utcnow():
            raise ValueError("as_of cannot be in the future")

        prediction = Prediction(
            id=uuid4().hex,
            thesis_id=thesis_id,
            target=target,
            horizon=horizon,
            probability=probability,
            quantiles=quantiles or {},
            model_version=model_version,
            features_hash=features_hash,
            as_of=as_of,
        )
        self.store.insert_prediction(prediction)
        return prediction

    def settle(
        self,
        prediction_id: str,
        *,
        realized_value: dict,
        source: str,
        realized_at: datetime,
        score: Optional[float] = None,
    ) -> Outcome:
        prediction = self.store.get_prediction(prediction_id)
        if prediction is None:
            raise KeyError(f"unknown prediction: {prediction_id}")
        if prediction.outcome_id is not None:
            raise ValueError(f"prediction already settled: {prediction_id}")

        outcome = Outcome(
            id=uuid4().hex,
            prediction_id=prediction_id,
            realized_value=realized_value,
            realized_at=realized_at,
            source=source,
            score=score,
        )
        self.store.insert_outcome(outcome)
        self.store.attach_outcome(prediction_id, outcome.id)
        return outcome

    def open_predictions(self) -> list[Prediction]:
        return self.store.list_predictions(open_only=True)
