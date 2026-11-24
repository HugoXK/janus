from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from janus.forecast.calibration import brier_score, expected_calibration_error
from janus.forecast.ledger import PredictionLedger
from janus.memory.store import JanusStore
from janus.thesis.tracker import ThesisTracker


def test_prediction_is_recorded_before_outcome_and_then_settled() -> None:
    store = JanusStore(":memory:")
    as_of = datetime(2026, 1, 1, tzinfo=timezone.utc)
    thesis = ThesisTracker(store).create(
        entity_id="ACME",
        statement="ACME holds its trend.",
        horizon="1M",
        as_of=as_of,
    )
    ledger = PredictionLedger(store)

    prediction = ledger.record(
        thesis_id=thesis.id,
        target="direction",
        horizon="1M",
        as_of=as_of,
        model_version="baseline-0.1",
        features_hash="abc",
        probability=0.7,
    )

    assert store.get_prediction(prediction.id).outcome_id is None

    outcome = ledger.settle(
        prediction.id,
        realized_value={"direction": "up"},
        source="test",
        realized_at=as_of + timedelta(days=30),
        score=1.0,
    )

    settled = store.get_prediction(prediction.id)
    assert settled.outcome_id == outcome.id
    assert store.get_outcome(outcome.id).score == 1.0


def test_cannot_settle_twice() -> None:
    store = JanusStore(":memory:")
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
        model_version="baseline-0.1",
        features_hash="abc",
        probability=0.6,
    )
    ledger.settle(
        prediction.id,
        realized_value={"direction": "down"},
        source="test",
        realized_at=as_of + timedelta(days=30),
    )

    with pytest.raises(ValueError, match="already settled"):
        ledger.settle(
            prediction.id,
            realized_value={"direction": "up"},
            source="test",
            realized_at=as_of + timedelta(days=31),
        )


def test_probability_must_be_in_range() -> None:
    store = JanusStore(":memory:")
    as_of = datetime(2026, 1, 1, tzinfo=timezone.utc)
    thesis = ThesisTracker(store).create(
        entity_id="ACME", statement="...", horizon="1M", as_of=as_of
    )
    ledger = PredictionLedger(store)

    with pytest.raises(ValueError, match="probability"):
        ledger.record(
            thesis_id=thesis.id,
            target="direction",
            horizon="1M",
            as_of=as_of,
            model_version="baseline-0.1",
            features_hash="abc",
            probability=1.5,
        )


def test_calibration_metrics() -> None:
    probabilities = [0.7, 0.2]
    outcomes = [1.0, 0.0]
    assert brier_score(probabilities, outcomes) == pytest.approx(0.065)
    assert 0.0 <= expected_calibration_error(probabilities, outcomes) <= 1.0
