from __future__ import annotations

from datetime import datetime, timezone

import pytest

from janus.forecast.ledger import PredictionLedger
from janus.memory.store import JanusStore
from janus.review.debrief import AttributionEngine, debrief_prediction
from janus.thesis.tracker import ThesisTracker


def _settled_prediction(store: JanusStore):
    as_of = datetime(2026, 1, 1, tzinfo=timezone.utc)
    thesis = ThesisTracker(store).create(
        entity_id="ACME", statement="...", horizon="1M", as_of=as_of
    )
    ledger = PredictionLedger(store)
    prediction = ledger.record(
        thesis_id=thesis.id,
        target="direction",
        horizon="1M",
        as_of=as_of,
        model_version="logit-v1",
        features_hash="features",
        probability=0.7,
    )
    ledger.settle(
        prediction.id,
        realized_value={"direction": "up"},
        source="test",
        realized_at=as_of,
        score=1.0,
    )
    return prediction


def test_attribution_sums_to_one() -> None:
    attribution = AttributionEngine().attribute(
        {"rsi_14": 70.0, "trend": 0.2, "breadth": 0.7, "valuation": 0.1},
        regime="risk-on",
    )
    assert sum(attribution.values()) == pytest.approx(1.0)


def test_debrief_prediction_is_stored() -> None:
    store = JanusStore(":memory:")
    prediction = _settled_prediction(store)

    review = debrief_prediction(
        store,
        prediction_id=prediction.id,
        features={"rsi_14": 70.0, "trend": 0.2, "breadth": 0.7},
        regime="risk-on",
        calibration=0.8,
        lessons="The trend signal helped.",
    )

    assert review.prediction_id == prediction.id
    assert review.calibration == 0.8
    assert sum(review.attribution.values()) == pytest.approx(1.0)
    assert store.list_reviews(prediction.id)[0].id == review.id


def test_debrief_requires_a_settled_prediction() -> None:
    store = JanusStore(":memory:")
    as_of = datetime(2026, 1, 1, tzinfo=timezone.utc)
    thesis = ThesisTracker(store).create(
        entity_id="ACME", statement="...", horizon="1M", as_of=as_of
    )
    prediction = PredictionLedger(store).record(
        thesis_id=thesis.id,
        target="direction",
        horizon="1M",
        as_of=as_of,
        model_version="logit-v1",
        features_hash="features",
        probability=0.7,
    )

    with pytest.raises(ValueError, match="not settled"):
        debrief_prediction(
            store,
            prediction_id=prediction.id,
            features={"rsi_14": 50.0},
        )
