from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from janus.forecast.ledger import PredictionLedger
from janus.memory.models import Observation, ObservationKind
from janus.memory.store import JanusStore
from janus.persona.profile import DIMENSIONS
from janus.persona.weighting import build_persona
from janus.review.counterfactual import CounterfactualLeak, CounterfactualReplay
from janus.thesis.tracker import ThesisTracker


def _profile(**overrides: float) -> dict[str, float]:
    profile = {dimension: 0.5 for dimension in DIMENSIONS}
    profile.update(overrides)
    return profile


def _fixture():
    store = JanusStore(":memory:")
    as_of = datetime(2026, 1, 1, tzinfo=timezone.utc)
    original_persona = build_persona(profile=_profile(quality=0.8), name="Quality")
    contre = build_persona(profile=_profile(contrarian=0.9), name="Contrarian")
    store.insert_persona(original_persona)
    store.insert_persona(contre)
    thesis = ThesisTracker(store).create(
        entity_id="ACME",
        statement="ACME trend continues",
        horizon="1M",
        as_of=as_of,
        persona_id=original_persona.id,
    )
    prediction = PredictionLedger(store).record(
        thesis_id=thesis.id,
        target="direction",
        horizon="1M",
        as_of=as_of,
        model_version="logit-v1",
        features_hash="abc",
        probability=0.7,
    )
    store.insert_observation(
        Observation(
            id="e1",
            entity_id="ACME",
            kind=ObservationKind.price,
            source="test",
            published_at=as_of - timedelta(days=1),
            value={"rsi_14": 70.0, "trend": 0.8, "breadth": 0.8},
            raw_hash="e1",
        )
    )
    store.insert_observation(
        Observation(
            id="future",
            entity_id="ACME",
            kind=ObservationKind.price,
            source="test",
            published_at=as_of + timedelta(days=1),
            value={"rsi_14": 5.0},
            raw_hash="future",
        )
    )
    return store, as_of, prediction, original_persona, contre


def test_replay_excludes_future_evidence_and_removes_ids() -> None:
    store, as_of, prediction, _, _ = _fixture()
    report = CounterfactualReplay(store).replay(
        prediction.id, remove_evidence=["e1"]
    )

    assert report.original.evidence_ids == ["e1"]
    assert "future" not in report.counterfactual.evidence_ids
    assert report.original.features == {"breadth": 0.8, "rsi_14": 70.0, "trend": 0.8}
    assert report.recorded_probability == 0.7
    assert report.counterfactual.probability == pytest.approx(0.5)
    assert report.delta < 0
    assert "e1" in report.explanation


def test_feature_overrides_and_persona_swap_change_the_delta() -> None:
    store, _, prediction, _, contre = _fixture()
    replay = CounterfactualReplay(store)

    overridden = replay.replay(
        prediction.id, feature_overrides={"trend": -1.0, "breadth": 0.1}
    )
    assert overridden.delta < 0
    assert overridden.feature_overrides == {"breadth": 0.1, "trend": -1.0}
    assert "Overrode features" in overridden.explanation

    tilted = replay.replay(prediction.id, persona_id=contre.id)
    assert tilted.counterfactual_persona_id == contre.id
    assert tilted.original_persona_id != contre.id
    assert tilted.delta > 0


def test_replay_is_deterministic() -> None:
    store, _, prediction, _, contre = _fixture()
    replay = CounterfactualReplay(store)
    first = replay.replay(prediction.id, persona_id=contre.id).to_dict()
    second = replay.replay(prediction.id, persona_id=contre.id).to_dict()
    assert first == second


def test_swapped_evidence_after_as_of_is_a_leak() -> None:
    store, as_of, prediction, _, _ = _fixture()
    leaked = Observation(
        id="later",
        entity_id="ACME",
        kind=ObservationKind.news,
        source="test",
        published_at=as_of + timedelta(hours=1),
        value={"rsi_14": 10.0},
        raw_hash="later",
    )
    with pytest.raises(CounterfactualLeak, match="published after"):
        CounterfactualReplay(store).replay(
            prediction.id, add_observations=[leaked]
        )


def test_expired_or_foreign_evidence_is_rejected() -> None:
    store, as_of, prediction, _, _ = _fixture()
    expired = Observation(
        id="expired",
        entity_id="ACME",
        kind=ObservationKind.news,
        source="test",
        published_at=as_of - timedelta(days=2),
        valid_to=as_of,
        value={"rsi_14": 10.0},
        raw_hash="expired",
    )
    with pytest.raises(CounterfactualLeak, match="expired"):
        CounterfactualReplay(store).replay(
            prediction.id, add_observations=[expired]
        )

    foreign = Observation(
        id="foreign",
        entity_id="OTHER",
        kind=ObservationKind.news,
        source="test",
        published_at=as_of - timedelta(days=2),
        value={"rsi_14": 10.0},
        raw_hash="foreign",
    )
    with pytest.raises(ValueError, match="belong to the prediction entity"):
        CounterfactualReplay(store).replay(
            prediction.id, add_observations=[foreign]
        )


def test_unknown_prediction_and_persona_fail_loudly() -> None:
    store, _, prediction, _, _ = _fixture()
    with pytest.raises(KeyError, match="unknown prediction"):
        CounterfactualReplay(store).replay("missing")
    with pytest.raises(KeyError, match="unknown persona"):
        CounterfactualReplay(store).replay(prediction.id, persona_id="missing")
