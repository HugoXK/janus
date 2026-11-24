from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from janus.memory.asof import assert_no_lookahead, observations_as_of
from janus.memory.models import Observation, ObservationKind
from janus.memory.store import JanusStore


def _obs(
    obs_id: str,
    published_at: datetime,
    *,
    value: float = 100.0,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
    observed_at: datetime | None = None,
    snapshot_id: str | None = None,
) -> Observation:
    return Observation(
        id=obs_id,
        entity_id="ACME",
        kind=ObservationKind.price,
        source="test",
        published_at=published_at,
        observed_at=observed_at or published_at,
        valid_from=valid_from,
        valid_to=valid_to,
        value={"close": value},
        raw_hash=obs_id,
        snapshot_id=snapshot_id,
    )


def test_as_of_excludes_future_expired_and_not_yet_valid() -> None:
    store = JanusStore(":memory:")
    as_of = datetime(2026, 1, 10, tzinfo=timezone.utc)

    store.insert_observation(_obs("past", as_of - timedelta(days=1)))
    store.insert_observation(_obs("future", as_of + timedelta(days=1)))
    store.insert_observation(
        _obs("not-yet-valid", as_of - timedelta(days=5), valid_from=as_of + timedelta(days=1))
    )
    store.insert_observation(
        _obs("expired", as_of - timedelta(days=10), valid_to=as_of - timedelta(days=2))
    )

    rows = store.query_observations_as_of("ACME", as_of)

    assert [row.id for row in rows] == ["past"]


def test_assert_no_lookahead_catches_future_rows() -> None:
    as_of = datetime(2026, 1, 10, tzinfo=timezone.utc)
    rows = [_obs("future", as_of + timedelta(days=1))]

    with pytest.raises(ValueError, match="lookahead detected"):
        assert_no_lookahead(rows, as_of)


def test_wrapper_uses_as_of_query() -> None:
    store = JanusStore(":memory:")
    as_of = datetime(2026, 1, 10, tzinfo=timezone.utc)
    store.insert_observation(_obs("past", as_of - timedelta(days=1)))
    store.insert_observation(_obs("future", as_of + timedelta(days=1)))

    rows = observations_as_of(store, "ACME", as_of)

    assert [row.id for row in rows] == ["past"]


def test_observed_mode_uses_ingest_time() -> None:
    store = JanusStore(":memory:")
    as_of = datetime(2026, 1, 10, tzinfo=timezone.utc)
    store.insert_observation(
        _obs(
            "late-published",
            as_of + timedelta(days=1),
            observed_at=as_of - timedelta(days=1),
        )
    )

    assert store.query_observations_as_of("ACME", as_of) == []
    observed = store.query_observations_as_of("ACME", as_of, mode="observed")
    assert [row.id for row in observed] == ["late-published"]


def test_snapshot_filter() -> None:
    store = JanusStore(":memory:")
    as_of = datetime(2026, 1, 10, tzinfo=timezone.utc)
    store.insert_observation(_obs("snap-1", as_of - timedelta(days=1), snapshot_id="s1"))
    store.insert_observation(_obs("snap-2", as_of - timedelta(days=1), snapshot_id="s2"))

    rows = store.query_observations_as_of("ACME", as_of, snapshot_id="s1")

    assert [row.id for row in rows] == ["snap-1"]


def test_pagination_is_stable() -> None:
    store = JanusStore(":memory:")
    as_of = datetime(2026, 1, 10, tzinfo=timezone.utc)
    store.insert_observation(_obs("b", as_of))
    store.insert_observation(_obs("a", as_of))

    first = store.query_observations_as_of("ACME", as_of, limit=1, offset=0)
    second = store.query_observations_as_of("ACME", as_of, limit=1, offset=1)

    assert [row.id for row in first] == ["a"]
    assert [row.id for row in second] == ["b"]


def test_invalid_mode_and_pagination_are_rejected() -> None:
    store = JanusStore(":memory:")
    as_of = datetime(2026, 1, 10, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="mode"):
        store.query_observations_as_of("ACME", as_of, mode="future")
    with pytest.raises(ValueError, match="limit"):
        store.query_observations_as_of("ACME", as_of, limit=-1)
    with pytest.raises(ValueError, match="offset"):
        store.query_observations_as_of("ACME", as_of, offset=-1)


def test_randomized_as_of_invariant() -> None:
    rng = random.Random(7)
    store = JanusStore(":memory:")
    as_of = datetime(2026, 1, 10, tzinfo=timezone.utc)
    expected = set()

    for index in range(200):
        offset = rng.randint(-10, 10)
        published = as_of + timedelta(days=offset)
        store.insert_observation(_obs(str(index), published))
        if offset <= 0:
            expected.add(str(index))

    rows = store.query_observations_as_of("ACME", as_of)

    assert {row.id for row in rows} == expected
    assert all(row.published_at <= as_of for row in rows)
