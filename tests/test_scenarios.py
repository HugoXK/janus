from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from janus.forecast.scenarios import (
    ScenarioBranch,
    ScenarioTree,
    generate_scenario_tree,
)


def test_generated_tree_sums_to_one_and_cites_evidence() -> None:
    tree = generate_scenario_tree(
        entity_id="ACME",
        horizon="1M",
        as_of=datetime(2026, 1, 2, tzinfo=timezone.utc),
        direction_probability=0.7,
        volatility=0.03,
        trend=0.4,
        evidence=["earnings surprise"],
    )

    assert [branch.name for branch in tree.branches] == ["up", "base", "down"]
    assert sum(branch.probability for branch in tree.branches) == pytest.approx(1.0)
    assert all(branch.falsifiers for branch in tree.branches)
    assert all(branch.evidence == ["earnings surprise"] for branch in tree.branches)
    assert tree.branches[0].probability > tree.branches[2].probability

    restored = ScenarioTree.model_validate_json(tree.model_dump_json())
    assert restored.entity_id == "ACME"


def test_invalid_probability_mass_is_rejected() -> None:
    branch = ScenarioBranch(
        name="up",
        probability=0.5,
        thesis="up",
        falsifiers=["down"],
        evidence=["trend"],
    )
    with pytest.raises(ValidationError, match="sum to 1"):
        ScenarioTree(
            entity_id="ACME",
            horizon="1M",
            as_of=datetime(2026, 1, 2, tzinfo=timezone.utc),
            direction_probability=0.5,
            volatility=0.02,
            branches=[branch],
        )


def test_every_branch_needs_a_falsifier_and_evidence() -> None:
    with pytest.raises(ValidationError, match="falsifier"):
        ScenarioBranch(name="up", probability=1.0, thesis="up", evidence=["x"])
    with pytest.raises(ValidationError, match="evidence"):
        ScenarioBranch(
            name="up", probability=1.0, thesis="up", falsifiers=["down"]
        )
