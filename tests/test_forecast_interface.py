from __future__ import annotations

from datetime import datetime, timezone

import pytest

from janus.mcp.service import JanusService
from janus.memory.store import JanusStore


def test_scenario_tree_tool_payload() -> None:
    service = JanusService(JanusStore(":memory:"))
    tree = service.scenario_tree(
        entity_id="ACME",
        horizon="1M",
        as_of="2026-01-01T00:00:00+00:00",
        direction_probability=0.65,
        volatility=0.025,
        evidence=["contract win"],
    )

    assert [branch["name"] for branch in tree["branches"]] == ["up", "base", "down"]
    assert sum(branch["probability"] for branch in tree["branches"]) == pytest.approx(1.0)
    assert all(branch["falsifiers"] for branch in tree["branches"])
    assert tree["as_of"].startswith("2026-01-01")


def test_quantile_tool_payload() -> None:
    service = JanusService(JanusStore(":memory:"))
    forecast = service.quantile_forecast(
        [-0.02, -0.01, 0.0, 0.01, 0.02], horizon=4
    )
    assert list(forecast["quantiles"]) == ["0.10", "0.50", "0.90"]
    assert forecast["width"] == pytest.approx(0.032 * 2)
    assert forecast["observations"] == 5


def test_scenario_tree_normalizes_naive_time() -> None:
    service = JanusService(JanusStore(":memory:"))
    tree = service.scenario_tree(
        entity_id="ACME",
        horizon="1M",
        as_of=datetime(2026, 1, 1),
        direction_probability=0.5,
    )
    assert tree["as_of"].startswith("2026-01-01")
