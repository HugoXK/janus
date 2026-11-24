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


def _prediction(store: JanusStore, target: str = "direction"):
    as_of = datetime(2026, 1, 1, tzinfo=timezone.utc)
    thesis = ThesisTracker(store).create(
        entity_id="ACME", statement="...", horizon="1M", as_of=as_of
    )
    return PredictionLedger(store).record(
        thesis_id=thesis.id,
        target=target,
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


def test_settle_down_and_flat() -> None:
    store = JanusStore(":memory:")
    service = SettlementService(store)

    down_prediction, as_of = _prediction(store)
    down = service.settle(
        down_prediction.id,
        DirectionOutcomeResolver(),
        start_price=100.0,
        end_price=90.0,
        source="test",
        realized_at=as_of,
    )
    assert down.score == 0.0
    assert down.realized_value["direction"] == "down"

    flat_prediction, as_of = _prediction(store)
    flat = service.settle(
        flat_prediction.id,
        DirectionOutcomeResolver(),
        start_price=100.0,
        end_price=100.0,
        source="test",
        realized_at=as_of,
    )
    assert flat.score == 0.0
    assert flat.realized_value["direction"] == "flat"


def test_wrong_target_is_rejected() -> None:
    store = JanusStore(":memory:")
    prediction, as_of = _prediction(store, target="return")

    with pytest.raises(ValueError, match="P\\(up\\)"):
        SettlementService(store).settle(
            prediction.id,
            DirectionOutcomeResolver(),
            start_price=100.0,
            end_price=110.0,
            source="test",
            realized_at=as_of,
        )

    assert store.get_prediction(prediction.id).outcome_id is None
