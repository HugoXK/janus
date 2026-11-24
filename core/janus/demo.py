from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from .analysis.indicators import rsi
from .forecast.calibration import brier_score, expected_calibration_error
from .forecast.ledger import PredictionLedger
from .memory.models import Observation, ObservationKind
from .memory.store import JanusStore
from .persona.profile import QUESTIONS, match_master, profile_from_answers
from .thesis.tracker import ThesisTracker


def run_demo() -> None:
    """A small, fully offline demonstration of the Janus loop."""

    store = JanusStore(":memory:")
    now = datetime(2026, 1, 31, tzinfo=timezone.utc)
    as_of = datetime(2026, 1, 15, tzinfo=timezone.utc)

    prices = [100.0 + index * 0.8 + (1.0 if index % 3 == 0 else 0.0) for index in range(20)]
    for index, close in enumerate(prices):
        published_at = as_of - timedelta(days=len(prices) - index)
        store.insert_observation(
            Observation(
                id=f"px-{index}",
                entity_id="ACME",
                kind=ObservationKind.price,
                source="demo",
                published_at=published_at,
                observed_at=now,
                value={"close": close},
                raw_hash=f"px-{index}",
            )
        )

    # This observation is in the database but must never appear in an as-of view.
    store.insert_observation(
        Observation(
            id="px-future",
            entity_id="ACME",
            kind=ObservationKind.price,
            source="demo",
            published_at=as_of + timedelta(days=1),
            observed_at=now,
            value={"close": 130.0},
            raw_hash="px-future",
        )
    )

    visible = store.query_observations_as_of("ACME", as_of, kind=ObservationKind.price)
    closes = pd.Series([row.value["close"] for row in visible], dtype=float)
    current_rsi = float(rsi(closes).iloc[-1])

    tracker = ThesisTracker(store)
    thesis = tracker.create(
        entity_id="ACME",
        statement="ACME remains constructive while RSI stays above 50 and price holds the 20-day trend.",
        horizon="1M",
        as_of=as_of,
        assumptions=["Demand remains stable", "No negative guidance surprise"],
        catalysts=["Upcoming earnings", "New product cycle"],
        risks=["Multiple compression", "Macro risk-off"],
        falsifiers=["RSI closes below 40", "Price closes below the 20-day average"],
    )

    ledger = PredictionLedger(store)
    prediction = ledger.record(
        thesis_id=thesis.id,
        target="direction",
        horizon="1M",
        as_of=as_of,
        model_version="baseline-0.1",
        features_hash="demo-features",
        probability=0.65,
    )
    ledger.settle(
        prediction.id,
        realized_value={"direction": "up"},
        source="demo",
        realized_at=as_of + timedelta(days=30),
        score=1.0,
    )

    probabilities = [0.65, 0.55, 0.80, 0.40, 0.70, 0.30]
    outcomes = [1.0, 1.0, 1.0, 0.0, 1.0, 0.0]

    answers = {question["id"]: len(question["options"]) // 2 for question in QUESTIONS}
    profile = profile_from_answers(answers)
    master, similarity = match_master(profile)

    print("Janus demo")
    print("=" * 60)
    print(f"as_of:                 {as_of.isoformat()}")
    print(f"observations visible:  {len(visible)} (future row excluded)")
    print(f"current RSI(14):       {current_rsi:.1f}")
    print(f"thesis:                {thesis.statement[:60]}...")
    print(f"prediction:            P(up over 1M) = {prediction.probability:.2f}")
    settled = store.get_prediction(prediction.id)
    is_settled = settled is not None and settled.outcome_id is not None
    print(f"prediction settled:    {is_settled}")
    print(f"brier score:           {brier_score(probabilities, outcomes):.4f}")
    print(f"expected calib. error: {expected_calibration_error(probabilities, outcomes):.4f}")
    print(f"taste match:           {master} ({similarity:.2f})")
    print("=" * 60)
    print("This demo is research tooling, not investment advice.")
