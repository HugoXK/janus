from __future__ import annotations

from datetime import datetime, timezone

import pytest

from janus.forecast.ledger import PredictionLedger
from janus.forecast.settlement import (
    DirectionOutcomeResolver,
    SettlementService,
    direction_label,
)
from janus.memory.store import JanusStore
from janus.thesis.tracker import ThesisTracker


def _prediction(store: JanusStore):
    as_of = datetime(2026, 1, 1, tzinfo=timezone.utc)
    thesis = ThesisTracker(store).create(
        entity_id="ACME", statement="...", horizon="1M", as_of=as_of
    )
    return PredictionLedger(store).record(
        thesis_id=thesis.id,
        target="direction",
        horizon="1M",
        as_of=as_of,
        model_version="logit-v1",
        features_hash="features",
        probability=0.7,
    ), as_of


def test_direction_label() -> None:
    assert direction_label(100.0, 110.0) == "up"
    assert direction_label(100.0, 90.0) == "down"
    assert direction_label(100.0, 100.0) == "flat"


def test_settle_direction_and_ledger() -> None:
    store = JanusStore(":memory:")
    prediction, as_of = _prediction(store)
    service = SettlementService(store)

    outcome = service.settle(
        prediction.id,
        DirectionOutcomeResolver(),
        start_price=100.0,
        end_price=110.0,
        source="test",
        realized_at=as_of,
    )

    assert outcome.score == 1.0
    assert outcome.realized_value["direction"] == "up"
    assert store.get_prediction(prediction.id).outcome_id == outcome.id
    assert len(store.settled_predictions()) == 1
    assert len(store.list_outcomes()) == 1

    with pytest.raises(ValueError, match="already settled"):
        service.settle(
            prediction.id,
            DirectionOutcomeResolver(),
            start_price=100.0,
            end_price=110.0,
            source="test",
            realized_at=as_of,
        )
