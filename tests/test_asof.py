from __future__ import annotations

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
) -> Observation:
    return Observation(
        id=obs_id,
        entity_id="ACME",
        kind=ObservationKind.price,
        source="test",
        published_at=published_at,
        observed_at=published_at,
        valid_from=valid_from,
        valid_to=valid_to,
        value={"close": value},
        raw_hash=obs_id,
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
