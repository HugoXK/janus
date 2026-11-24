from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from janus.eval.baselines import run_baselines
from janus.eval.beliefbench import BeliefBench, Scenario, ScenarioResult


def _scenario(
    scenario_id: str,
    outcome: float,
    *,
    horizon: str = "1M",
    tags: tuple[str, ...] = ("tech",),
) -> Scenario:
    return Scenario(
        id=scenario_id,
        entity_id="ACME",
        as_of=datetime(2026, 1, 1, tzinfo=timezone.utc),
        resolved_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        question="Did ACME rise?",
        resolution={"outcome": outcome},
        horizon=horizon,
        tags=tags,
    )


def _bench() -> BeliefBench:
    bench = BeliefBench()
    bench.add(_scenario("a", 1.0))
    bench.add(_scenario("b", 0.0, horizon="1W"))
    bench.add(_scenario("c", 1.0, tags=("macro",)))
    return bench


def test_run_reports_metrics_and_slices() -> None:
    def runner(scenario: Scenario) -> ScenarioResult:
        return ScenarioResult(
            scenario_id=scenario.id,
            probability=0.7,
            outcome=float(scenario.resolution["outcome"]),
            evidence=("news:1",),
        )

    report = _bench().run(runner)

    assert report.n == 3
    assert report.brier == pytest.approx((0.09 + 0.49 + 0.09) / 3)
    assert report.directional_accuracy == pytest.approx(2 / 3)
    assert report.citation_coverage == 1.0
    assert report.by_horizon["1M"]["n"] == 2.0
    assert report.by_horizon["1W"]["n"] == 1.0
    assert report.by_tag["tech"]["n"] == 2.0
    assert report.by_tag["macro"]["n"] == 1.0


def test_resolution_must_be_after_as_of() -> None:
    with pytest.raises(ValueError, match="resolved_at"):
        Scenario(
            id="bad",
            entity_id="ACME",
            as_of=datetime(2026, 2, 1, tzinfo=timezone.utc),
            resolved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            question="...",
            resolution={"outcome": 1.0},
        )


def test_save_and_load(tmp_path) -> None:
    bench = _bench()
    path = bench.save(tmp_path / "bench.json")
    loaded = BeliefBench.load(path)

    assert [scenario.id for scenario in loaded.scenarios] == ["a", "b", "c"]
    assert loaded.scenarios[0].tags == ("tech",)


def test_load_rejects_duplicate_ids(tmp_path) -> None:
    scenario = _scenario("dup", 1.0)
    path = tmp_path / "duplicate.json"
    path.write_text(
        json.dumps({"scenarios": [scenario.to_dict(), scenario.to_dict()]})
    )

    with pytest.raises(ValueError, match="duplicate"):
        BeliefBench.load(path)


def test_baselines_are_reproducible() -> None:
    bench = _bench()
    reports = run_baselines(bench)

    always_up = reports["always_up"]
    assert always_up.brier == pytest.approx(1 / 3)
    assert always_up.directional_accuracy == pytest.approx(2 / 3)
    assert reports["always_down"].directional_accuracy == pytest.approx(1 / 3)
    assert reports["random"].n == 3


def test_runner_validation() -> None:
    bench = _bench()

    with pytest.raises(ValueError, match="probability"):
        bench.run(
            lambda scenario: ScenarioResult(
                scenario_id=scenario.id,
                probability=2.0,
                outcome=1.0,
            )
        )

    with pytest.raises(ValueError, match="outcome"):
        bench.run(
            lambda scenario: ScenarioResult(
                scenario_id=scenario.id,
                probability=0.5,
                outcome=2.0,
            )
        )
