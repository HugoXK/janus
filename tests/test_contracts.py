from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from janus.contracts import CONTRACT_MODELS, SCHEMA_VERSION, export_schema
from janus.memory.models import Observation, ObservationKind
from janus.memory.store import JanusStore

ROOT = Path(__file__).resolve().parents[1]


def test_schema_version_is_positive() -> None:
    assert SCHEMA_VERSION >= 1


def test_exported_schema_contains_every_contract_model() -> None:
    schema = export_schema()
    assert set(schema["$defs"]) == set(CONTRACT_MODELS)
    assert schema["schema_version"] == SCHEMA_VERSION


def test_checked_in_schema_matches_the_models() -> None:
    path = ROOT / "schemas" / "janus.schema.json"
    assert path.exists(), "run `janus schema export` and commit the result"
    assert json.loads(path.read_text()) == export_schema()


def test_observation_required_fields() -> None:
    observation = export_schema()["$defs"]["Observation"]
    required = set(observation["required"])
    assert {
        "id",
        "entity_id",
        "kind",
        "source",
        "published_at",
        "value",
        "raw_hash",
    } <= required


def test_prediction_required_fields() -> None:
    prediction = export_schema()["$defs"]["Prediction"]
    required = set(prediction["required"])
    assert {
        "id",
        "thesis_id",
        "target",
        "horizon",
        "model_version",
        "features_hash",
        "as_of",
    } <= required


def test_naive_timestamps_are_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        Observation(
            id="naive",
            entity_id="ACME",
            kind=ObservationKind.price,
            source="test",
            published_at=datetime(2026, 1, 1),
            value={"close": 100.0},
            raw_hash="naive",
        )


def test_timestamps_are_normalized_to_utc() -> None:
    published = datetime(2026, 1, 1, 9, 30, tzinfo=timezone(timedelta(hours=8)))
    observation = Observation(
        id="utc",
        entity_id="ACME",
        kind=ObservationKind.price,
        source="test",
        published_at=published,
        value={"close": 100.0},
        raw_hash="utc",
    )
    assert observation.published_at.utcoffset() == timedelta(0)
    assert observation.published_at == datetime(2026, 1, 1, 1, 30, tzinfo=timezone.utc)


def test_prediction_has_no_update_path() -> None:
    assert hasattr(JanusStore, "attach_outcome")
    assert not hasattr(JanusStore, "update_prediction")
