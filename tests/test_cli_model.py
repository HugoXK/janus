"""`janus model` CLI: read-only inspection of the artifact store (AC9-AC11).

Contract: issue #39 scope comment 7150443549 plus amendment A4 (7150553996).
Every invocation redirects the store with JANUS_HOME=tmp_path.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from janus.cli import app
from janus.forecast.baseline import LogisticDirectionModel
from janus.forecast.registry import ModelArtifact, ModelRegistry

FEATURES = {"rsi_14": 61.5, "trend": 0.42, "breadth": 0.55}
runner = CliRunner()


def _fitted_model() -> LogisticDirectionModel:
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


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("JANUS_HOME", str(tmp_path))
    return tmp_path


def _artifact(home: Path, **overrides: object) -> ModelArtifact:
    registry = ModelRegistry(root=home / "models")
    kwargs: dict[str, object] = {
        "features": dict(FEATURES),
        "data_snapshot": "snap-2026-01-02",
        "code_version": "abc1234",
    }
    kwargs.update(overrides)
    return registry.save(_fitted_model(), **kwargs)  # type: ignore[arg-type]


# AC9 -----------------------------------------------------------------------


def test_list_text_mode_on_an_empty_store_exits_zero(home: Path) -> None:
    result = runner.invoke(app, ["model", "list"])

    assert result.exit_code == 0, result.output
    assert result.output.strip() == ""


def test_list_text_mode_prints_id_version_timestamp_and_hash(home: Path) -> None:
    artifact = _artifact(home)

    result = runner.invoke(app, ["model", "list"])

    assert result.exit_code == 0, result.output
    line = result.output.strip()
    assert artifact.artifact_id[:12] in line
    assert artifact.version in line
    assert artifact.features_hash[:12] in line
    assert artifact.created_at in line


def test_list_json_mode_on_an_empty_store_prints_an_empty_array(home: Path) -> None:
    result = runner.invoke(app, ["model", "list", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == []


def test_list_json_mode_shape(home: Path) -> None:
    artifact = _artifact(home)

    result = runner.invoke(app, ["model", "list", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert isinstance(payload, list) and len(payload) == 1
    item = payload[0]
    assert item["artifact_id"] == artifact.artifact_id
    assert item["version"] == artifact.version
    assert item["created_at"] == artifact.created_at
    assert item["features_hash"] == artifact.features_hash
    assert item["model"] == {"name": "logistic-direction", "version": "logit-v1"}


def test_list_is_non_fatal_with_a_corrupt_file(home: Path) -> None:
    artifact = _artifact(home)
    (home / "models" / "badc0ffee000.json").write_text("{not json", encoding="utf-8")

    result = runner.invoke(app, ["model", "list"])

    assert result.exit_code == 0, result.output
    assert artifact.artifact_id[:12] in result.output


# AC10 ----------------------------------------------------------------------


def test_show_text_mode_resolves_a_ref_prefix(home: Path) -> None:
    artifact = _artifact(home)

    result = runner.invoke(app, ["model", "show", artifact.artifact_id[:12]])

    assert result.exit_code == 0, result.output
    out = result.output
    assert artifact.version in out
    assert artifact.artifact_id in out
    assert artifact.features_hash in out
    assert "snap-2026-01-02" in out
    assert "abc1234" in out
    assert "logistic-direction" in out


def test_show_json_mode_prints_the_nine_fields(home: Path) -> None:
    artifact = _artifact(home)

    result = runner.invoke(app, ["model", "show", artifact.artifact_id, "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert set(payload) == {
        "artifact_id",
        "version",
        "created_at",
        "features",
        "features_hash",
        "data_snapshot",
        "code_version",
        "card",
        "params",
    }
    assert payload["artifact_id"] == artifact.artifact_id
    assert payload["features"] == FEATURES
    assert payload["features_hash"] == artifact.features_hash
    assert payload["card"]["version"] == "logit-v1"
    assert payload["params"]


def test_show_unknown_ref_exits_one_with_the_not_found_line(home: Path) -> None:
    _artifact(home)
    root = home / "models"

    result = runner.invoke(app, ["model", "show", "deadbeef"])

    assert result.exit_code == 1
    assert result.stderr.strip() == f"artifact not found: deadbeef (store: {root})"


def test_show_corrupt_artifact_exits_one_with_the_corrupt_line(home: Path) -> None:
    (home / "models").mkdir(parents=True, exist_ok=True)
    broken = home / "models" / "badc0ffee000.json"
    broken.write_text("{not json", encoding="utf-8")

    result = runner.invoke(app, ["model", "show", "badc0ffee"])

    assert result.exit_code == 1
    assert result.stderr.strip() == f"artifact corrupt: {broken}"


# AC11 ----------------------------------------------------------------------


def test_commands_use_janus_home_and_never_the_real_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_home = tmp_path / "redirected"
    monkeypatch.setenv("JANUS_HOME", str(store_home))
    artifact = _artifact(store_home)

    result = runner.invoke(app, ["model", "show", artifact.artifact_id, "--json"])

    assert result.exit_code == 0, result.output
    assert (store_home / "models" / f"{artifact.artifact_id}.json").is_file()
    assert json.loads(result.output)["artifact_id"] == artifact.artifact_id
