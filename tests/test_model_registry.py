"""Model registry: content-addressed forecast artifacts (AC1-AC8).

Contract: issue #39 scope comment 7150443549, amendment A1-A4 in 7150553996.
Offline, deterministic, no network, no sleeps; every store lives in tmp_path.
"""

from __future__ import annotations

import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from janus.analysis.features import features_hash
from janus.forecast.baseline import LogisticDirectionModel
from janus.forecast.ledger import PredictionLedger
from janus.forecast.registry import (
    ArtifactCorruptError,
    ArtifactNotFoundError,
    FeatureHashMismatchError,
    ModelArtifact,
    ModelRegistry,
    model_ref,
)
from janus.memory.store import JanusStore
from janus.thesis.tracker import ThesisTracker

FEATURES = {"rsi_14": 61.5, "trend": 0.42, "breadth": 0.55}


def _fitted_model() -> LogisticDirectionModel:
    """A small deterministic fit; the coefficients must round-trip through JSON."""

    rng = np.random.default_rng(7)
    rows = []
    outcomes = []
    for _ in range(96):
        rsi = float(rng.uniform(0.0, 100.0))
        trend = float(rng.uniform(-1.0, 1.0))
        breadth = float(rng.uniform(0.0, 1.0))
        rows.append([rsi, trend, breadth])
        outcomes.append(1.0 if (rsi - 50.0) / 50.0 + trend + (breadth - 0.5) > 0 else 0.0)
    model = LogisticDirectionModel(epochs=200)
    model.fit(rows, outcomes)
    return model


def _registry(tmp_path: Path) -> ModelRegistry:
    return ModelRegistry(root=tmp_path / "models")


def _save(registry: ModelRegistry, **overrides: object) -> ModelArtifact:
    model = _fitted_model()
    kwargs: dict[str, object] = {
        "features": dict(FEATURES),
        "data_snapshot": "snap-2026-01-02",
        "code_version": "abc1234",
    }
    kwargs.update(overrides)
    return registry.save(model, **kwargs)  # type: ignore[arg-type]


# AC1 -----------------------------------------------------------------------


def test_save_writes_one_canonical_file_and_load_round_trips(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    artifact = _save(registry)

    assert isinstance(artifact, ModelArtifact)
    assert len(artifact.artifact_id) == 64
    assert all(char in "0123456789abcdef" for char in artifact.artifact_id)
    assert artifact.features == FEATURES
    assert artifact.features_hash == features_hash(FEATURES)
    assert artifact.data_snapshot == "snap-2026-01-02"
    assert artifact.code_version == "abc1234"
    # version defaults to the model card version.
    assert artifact.version == "logit-v1"
    stamp = datetime.fromisoformat(artifact.created_at)
    assert stamp.tzinfo is not None

    files = sorted((tmp_path / "models").glob("*.json"))
    assert [path.name for path in files] == [f"{artifact.artifact_id}.json"]

    loaded = registry.load(artifact.artifact_id)
    assert loaded == artifact
    assert loaded.model.card is not None
    assert loaded.model.card.version == "logit-v1"
    assert tuple(loaded.model.features) == ("rsi_14", "trend", "breadth")
    assert loaded.model.predict_one(
        rsi_value=FEATURES["rsi_14"], trend=FEATURES["trend"], breadth=FEATURES["breadth"]
    ) == artifact.model.predict_one(
        rsi_value=FEATURES["rsi_14"], trend=FEATURES["trend"], breadth=FEATURES["breadth"]
    )


def test_artifact_id_ignores_created_at_and_is_idempotent(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    first = _save(registry)
    second = _save(registry)

    assert first.artifact_id == second.artifact_id
    assert len(list((tmp_path / "models").glob("*.json"))) == 1
    assert [item.artifact_id for item in registry.list()] == [first.artifact_id]


def test_default_root_follows_janus_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JANUS_HOME", str(tmp_path))
    artifact = _save(ModelRegistry())

    assert (tmp_path / "models" / f"{artifact.artifact_id}.json").is_file()
    assert ModelRegistry().load(artifact.artifact_id) == artifact


# AC4 -----------------------------------------------------------------------


def test_load_accepts_full_id_prefix_and_version(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    artifact = _save(registry, version="logit-2026-01")

    assert registry.load(artifact.artifact_id) == artifact
    assert registry.load(artifact.artifact_id[:12]) == artifact
    assert registry.load(artifact.artifact_id[:4]) == artifact
    assert registry.load("logit-2026-01") == artifact


# AC4 + A1 ------------------------------------------------------------------


def test_unknown_ref_raises_not_found_with_exact_message(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    _save(registry)
    root = tmp_path / "models"

    with pytest.raises(ArtifactNotFoundError) as excinfo:
        registry.load("deadbeef")

    assert isinstance(excinfo.value, LookupError)
    assert str(excinfo.value) == f"artifact not found: deadbeef (store: {root})"


def test_ambiguous_version_raises_not_found_naming_candidates(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    first = _save(registry, features={"rsi_14": 10.0, "trend": -0.5, "breadth": 0.2})
    second = _save(registry, features={"rsi_14": 90.0, "trend": 0.9, "breadth": 0.8})
    assert first.version == second.version == "logit-v1"

    with pytest.raises(ArtifactNotFoundError) as excinfo:
        registry.load("logit-v1")

    message = str(excinfo.value)
    assert message.startswith("artifact not found: logit-v1 (store: ")
    assert "ambiguous" in message
    for candidate in sorted({first.artifact_id, second.artifact_id}):
        assert candidate in message


def test_ambiguous_id_prefix_raises_not_found_naming_candidates(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    model = _fitted_model()

    # Deterministic scan for a real 4-hex collision; stops at the first one, so
    # exactly two stored ids share that prefix.
    seen: dict[str, str] = {}
    pair: tuple[str, str] | None = None
    for index in range(2000):
        artifact = registry.save(
            model,
            features={"rsi_14": float(index), "trend": 0.0, "breadth": 0.5},
            version=f"scan-{index}",
        )
        prefix = artifact.artifact_id[:4]
        if prefix in seen:
            pair = (seen[prefix], artifact.artifact_id)
            break
        seen[prefix] = artifact.artifact_id

    assert pair is not None, "expected a 4-hex id collision within 2000 artifacts"
    prefix = pair[0][:4]
    assert pair[0][:4] == pair[1][:4]

    with pytest.raises(ArtifactNotFoundError) as excinfo:
        registry.load(prefix)

    message = str(excinfo.value)
    assert message.startswith(f"artifact not found: {prefix} (store: ")
    assert "ambiguous" in message
    for candidate in sorted(pair):
        assert candidate in message


# AC6 -----------------------------------------------------------------------


def test_replay_is_exactly_equal_to_predict_one(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    artifact = _save(registry)
    expected = artifact.model.predict_one(
        rsi_value=FEATURES["rsi_14"], trend=FEATURES["trend"], breadth=FEATURES["breadth"]
    )

    assert registry.replay(artifact.artifact_id) == expected
    # A2: an already-loaded artifact replays to the identical float.
    assert registry.replay(artifact) == expected
    # features=None falls back to the stored vector; passing it is the same.
    assert registry.replay(artifact.artifact_id, features=dict(FEATURES)) == expected

    # A fresh registry that only sees the file on disk must agree too (JSON float
    # round-trip, not process memory).
    reopened = ModelRegistry(root=tmp_path / "models")
    assert reopened.replay(artifact.artifact_id) == expected


def test_replay_with_foreign_features_raises_hash_mismatch(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    artifact = _save(registry)

    with pytest.raises(FeatureHashMismatchError) as excinfo:
        registry.replay(
            artifact.artifact_id,
            features={"rsi_14": 1.0, "trend": 0.0, "breadth": 0.0},
        )

    assert isinstance(excinfo.value, ValueError)


# AC7 / AC8 ----------------------------------------------------------------


def test_ledger_prediction_replays_to_the_recorded_probability(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    artifact = _save(registry)
    reference = model_ref(artifact)
    assert reference == f"{artifact.version}@{artifact.artifact_id[:12]}"

    store = JanusStore(":memory:")
    as_of = datetime(2026, 1, 2, tzinfo=timezone.utc)
    thesis = ThesisTracker(store).create(
        entity_id="ACME", statement="ACME holds its trend.", horizon="1M", as_of=as_of
    )
    probability = registry.replay(artifact)
    prediction = PredictionLedger(store).record(
        thesis_id=thesis.id,
        target="direction",
        horizon="1M",
        as_of=as_of,
        model_version=reference,
        features_hash=artifact.features_hash,
        probability=probability,
    )

    resolved = registry.resolve_prediction(prediction)
    assert resolved.artifact_id == artifact.artifact_id
    # Exact equality through the SQLite float round-trip: no tolerance.
    assert registry.replay(resolved) == prediction.probability


def test_pre_registry_prediction_raises_not_found(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    _save(registry)

    store = JanusStore(":memory:")
    as_of = datetime(2026, 1, 2, tzinfo=timezone.utc)
    thesis = ThesisTracker(store).create(
        entity_id="ACME", statement="ACME holds its trend.", horizon="1M", as_of=as_of
    )
    prediction = PredictionLedger(store).record(
        thesis_id=thesis.id,
        target="direction",
        horizon="1M",
        as_of=as_of,
        model_version="baseline-0.1",
        features_hash=features_hash(dict(FEATURES)),
        probability=0.5,
    )

    with pytest.raises(ArtifactNotFoundError):
        registry.resolve_prediction(prediction)


def test_resolve_prediction_rejects_a_swapped_feature_hash(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    artifact = _save(registry)

    store = JanusStore(":memory:")
    as_of = datetime(2026, 1, 2, tzinfo=timezone.utc)
    thesis = ThesisTracker(store).create(
        entity_id="ACME", statement="ACME holds its trend.", horizon="1M", as_of=as_of
    )
    prediction = PredictionLedger(store).record(
        thesis_id=thesis.id,
        target="direction",
        horizon="1M",
        as_of=as_of,
        model_version=model_ref(artifact),
        features_hash=features_hash({"rsi_14": 1.0, "trend": 0.0, "breadth": 0.0}),
        probability=0.5,
    )

    with pytest.raises(FeatureHashMismatchError):
        registry.resolve_prediction(prediction)


# AC5 -----------------------------------------------------------------------


def test_list_skips_corrupt_files_with_a_warning(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    good = _save(registry)
    broken = tmp_path / "models" / "badc0ffee000.json"
    broken.write_text("{not json", encoding="utf-8")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        listed = registry.list()

    assert [item.artifact_id for item in listed] == [good.artifact_id]
    assert len(caught) >= 1


def test_load_of_unparsable_file_raises_corrupt(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    broken = tmp_path / "models" / "badc0ffee000.json"
    broken.write_text("{not json", encoding="utf-8")

    with pytest.raises(ArtifactCorruptError):
        registry.load("badc0ffee")


def test_load_of_tampered_file_raises_corrupt(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    artifact = _save(registry)
    path = tmp_path / "models" / f"{artifact.artifact_id}.json"
    tampered = path.read_text(encoding="utf-8").replace("61.5", "62.5")
    assert tampered != path.read_text(encoding="utf-8")
    path.write_text(tampered, encoding="utf-8")

    with pytest.raises(ArtifactCorruptError):
        registry.load(artifact.artifact_id)
