from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from janus.memory.conflicts import (
    OverrideStore,
    apply_override,
    detect_conflicts,
    scan_store,
    source_tier,
)
from janus.memory.models import Observation, ObservationKind
from janus.memory.store import JanusStore


def _obs(
    obs_id: str,
    source: str,
    value: float,
    *,
    published_at: datetime | None = None,
    confidence: float = 1.0,
    fact: str = "eps",
    entity_id: str = "ACME",
) -> Observation:
    return Observation(
        id=obs_id,
        entity_id=entity_id,
        kind=ObservationKind.fundamental,
        source=source,
        published_at=published_at or datetime(2026, 1, 1, tzinfo=timezone.utc),
        value={"fact": fact, "value": value},
        confidence=confidence,
        raw_hash=f"hash:{obs_id}",
    )


def _group(observations):
    groups = detect_conflicts(observations)
    assert len(groups) == 1
    return groups[0]


def test_source_tiers_are_documented_and_prefix_aware() -> None:
    assert source_tier("sec_edgar") == 1.0
    assert source_tier("sec:filing") == 1.0
    assert source_tier("rss:ir") == 0.65
    assert source_tier("unknown") == 0.5


def test_conflict_keeps_both_values_and_prefers_tier() -> None:
    group = _group([_obs("rss", "rss", 1.0), _obs("sec", "sec_edgar", 2.0)])

    assert group.selected_id == "sec"
    assert {value.observation_id for value in group.values} == {"rss", "sec"}
    assert group.resolution == "resolved"
    assert "tier=1.00" in group.reason


def test_identical_values_are_corroboration_not_conflict() -> None:
    assert detect_conflicts([_obs("a", "rss", 1.0), _obs("b", "sec_edgar", 1.0)]) == []


def test_same_tier_and_time_is_unresolved() -> None:
    group = _group([_obs("a", "rss", 1.0), _obs("b", "rss", 2.0)])
    assert group.selected_id is None
    assert group.resolution == "unresolved"


def test_newer_observation_wins_within_a_tier() -> None:
    older = datetime(2026, 1, 1, tzinfo=timezone.utc)
    newer = older + timedelta(days=1)
    group = _group(
        [_obs("old", "rss", 1.0, published_at=older), _obs("new", "rss", 2.0, published_at=newer)]
    )
    assert group.selected_id == "new"


def test_corroboration_breaks_a_tier_tie() -> None:
    group = _group(
        [
            _obs("a", "rss", 1.0),
            _obs("b", "rss", 1.0),
            _obs("c", "rss", 2.0),
        ]
    )
    assert group.selected_id in {"a", "b"}
    assert "corroboration=2" in group.reason


def test_override_is_audited_and_applied(tmp_path) -> None:
    group = _group([_obs("rss", "rss", 1.0), _obs("sec", "sec_edgar", 2.0)])
    store = OverrideStore(tmp_path / "overrides.jsonl")
    record = store.record(
        group,
        selected_observation_id="rss",
        actor="alice",
        reason="manual review",
    )

    assert record.alternatives == ("sec",)
    assert store.list()[-1] == record
    assert store.latest("ACME", "fundamental", "eps") == record
    applied = apply_override(group, record)
    assert applied.selected_id == "rss"
    assert applied.resolution == "override"
    assert "manual review" in applied.reason


def test_override_rejects_unknown_observation(tmp_path) -> None:
    group = _group([_obs("a", "rss", 1.0), _obs("b", "rss", 2.0)])
    with pytest.raises(ValueError, match="outside the conflict"):
        OverrideStore(tmp_path / "overrides.jsonl").record(
            group, selected_observation_id="missing", actor="alice", reason=""
        )


def test_scan_store_respects_as_of() -> None:
    store = JanusStore(":memory:")
    as_of = datetime(2026, 1, 5, tzinfo=timezone.utc)
    store.insert_observation(_obs("rss", "rss", 1.0))
    store.insert_observation(_obs("sec", "sec_edgar", 2.0))
    store.insert_observation(
        _obs(
            "future",
            "sec_edgar",
            3.0,
            published_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        )
    )

    group = scan_store(store, "ACME", as_of)[0]
    assert {value.observation_id for value in group.values} == {"rss", "sec"}
    assert group.selected_id == "sec"


def test_unkeyed_observations_do_not_conflict() -> None:
    no_key = Observation(
        id="news",
        entity_id="ACME",
        kind=ObservationKind.news,
        source="rss",
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        value={"title": "a headline"},
        raw_hash="news",
    )
    assert detect_conflicts([no_key, no_key]) == []


def test_source_tier_normalizes_case_and_separators() -> None:
    assert source_tier("SEC-EDGAR") == 1.0
    assert source_tier("Sec-Edgar:filing") == 1.0
    assert source_tier("FRED") == 0.95


def test_number_zero_fact_key_is_still_a_fact() -> None:
    groups = detect_conflicts(
        [
            _obs("a", "rss", 1.0, fact=0),
            _obs("b", "sec_edgar", 2.0, fact=0),
        ]
    )
    assert len(groups) == 1
    assert groups[0].fact_key == "0"


def test_stale_override_is_not_applied(tmp_path) -> None:
    original = _group([_obs("a", "rss", 1.0), _obs("b", "rss", 2.0)])
    store = OverrideStore(tmp_path / "overrides.jsonl")
    record = store.record(
        original, selected_observation_id="b", actor="alice", reason="manual review"
    )

    rebuilt = _group([_obs("a", "rss", 1.0), _obs("c", "sec_edgar", 2.0)])
    applied = apply_override(rebuilt, record)

    assert applied.resolution == "stale"
    assert applied.selected_id is None
    assert "stale override: b is not part of this conflict" in applied.reason


def test_audit_skips_unparseable_lines_and_reports_count(tmp_path) -> None:
    path = tmp_path / "overrides.jsonl"
    store = OverrideStore(path)
    first = store.record(
        _group([_obs("a", "rss", 1.0), _obs("b", "rss", 2.0)]),
        selected_observation_id="a",
        actor="alice",
        reason="first",
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write("not-json\n")
    second = store.record(
        _group([_obs("c", "rss", 1.0), _obs("d", "rss", 2.0)]),
        selected_observation_id="c",
        actor="alice",
        reason="second",
    )

    records = store.list()
    assert [record.id for record in records] == [first.id, second.id]
    assert store.skipped_lines == 1
    assert store.latest("ACME", "fundamental", "eps") == second


def test_auxiliary_payload_keys_define_the_fact() -> None:
    first = _obs("a", "rss", 1.0)
    first.value["note"] = "restated"
    second = _obs("b", "sec_edgar", 1.0)

    group = _group([first, second])
    assert {value.observation_id for value in group.values} == {"a", "b"}
    assert group.selected_id == "b"
