from __future__ import annotations

from datetime import datetime, timezone

import pytest

from janus.forecast.calibration import brier_score
from janus.forecast.calibration_service import (
    CalibrationService,
    IsotonicCalibrator,
    PlattCalibrator,
)
from janus.forecast.ledger import PredictionLedger
from janus.memory.store import JanusStore
from janus.thesis.tracker import ThesisTracker


def test_platt_reduces_overconfidence_and_round_trips() -> None:
    probabilities = [0.9, 0.9, 0.1, 0.1]
    outcomes = [1.0, 0.0, 0.0, 1.0]
    before = brier_score(probabilities, outcomes)

    calibrator = PlattCalibrator().fit(probabilities, outcomes)
    transformed = [calibrator.transform(value) for value in probabilities]

    assert all(0.0 <= value <= 1.0 for value in transformed)
    assert brier_score(transformed, outcomes) < before

    clone = PlattCalibrator.from_dict(calibrator.to_dict())
    assert clone.transform(0.9) == pytest.approx(calibrator.transform(0.9))


def test_isotonic_is_monotonic() -> None:
    calibrator = IsotonicCalibrator().fit(
        [0.1, 0.2, 0.3, 0.7, 0.8, 0.9],
        [0.0, 0.0, 0.0, 1.0, 1.0, 1.0],
    )
    transformed = [
        calibrator.transform(value) for value in [0.1, 0.2, 0.3, 0.7, 0.8, 0.9]
    ]

    assert transformed == sorted(transformed)
    assert all(0.0 <= value <= 1.0 for value in transformed)


def test_report_groups_by_metadata() -> None:
    service = CalibrationService()
    report = service.report(
        [0.7, 0.4, 0.8],
        [1.0, 0.0, 1.0],
        [
            {"regime": "risk-on", "horizon": "1M", "persona": "Buffett"},
            {"regime": "risk-off", "horizon": "1W", "persona": "Soros"},
            {"regime": "risk-on", "horizon": "1M", "persona": "Buffett"},
        ],
    )

    assert report.n == 3
    assert report.by_regime["risk-on"]["n"] == 2.0
    assert report.by_horizon["1M"]["n"] == 2.0
    assert report.by_persona["Buffett"]["n"] == 2.0


def test_report_from_store() -> None:
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

    report = CalibrationService.from_store(store)

    assert report.n == 1
    assert report.by_horizon["1M"]["n"] == 1.0
