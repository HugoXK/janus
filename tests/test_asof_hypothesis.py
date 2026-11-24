from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

hypothesis = pytest.importorskip("hypothesis")

from hypothesis import given, settings, strategies as st  # noqa: E402

from janus.memory.models import Observation, ObservationKind  # noqa: E402
from janus.memory.store import JanusStore  # noqa: E402

AWARE = st.datetimes(
    timezones=st.just(timezone.utc),
    min_value=datetime(2000, 1, 1, tzinfo=timezone.utc),
    max_value=datetime(2030, 1, 1, tzinfo=timezone.utc),
)


def _observation(obs_id: str, published_at: datetime, **kwargs: object) -> Observation:
    return Observation(
        id=obs_id,
        entity_id="ACME",
        kind=ObservationKind.price,
        source="property",
        published_at=published_at,
        value={"close": 100.0},
        raw_hash=obs_id,
        **kwargs,
    )


@settings(max_examples=40, deadline=None)
@given(
    as_of=AWARE,
    offsets=st.lists(
        st.integers(min_value=-365, max_value=365),
        min_size=0,
        max_size=40,
    ),
)
def test_future_rows_are_never_returned(as_of: datetime, offsets: list[int]) -> None:
    store = JanusStore(":memory:")
    expected = set()
    for index, offset in enumerate(offsets):
        published = as_of + timedelta(days=offset)
        store.insert_observation(_observation(str(index), published))
        if offset <= 0:
            expected.add(str(index))

    rows = store.query_observations_as_of("ACME", as_of)

    assert {row.id for row in rows} == expected
    assert all(row.published_at <= as_of for row in rows)


@settings(max_examples=40, deadline=None)
@given(
    as_of=AWARE,
    start_offset=st.integers(min_value=-30, max_value=30),
    length=st.integers(min_value=1, max_value=60),
)
def test_validity_window_is_respected(
    as_of: datetime, start_offset: int, length: int
) -> None:
    valid_from = as_of + timedelta(days=start_offset)
    valid_to = valid_from + timedelta(days=length)
    store = JanusStore(":memory:")
    store.insert_observation(
        _observation(
            "window",
            as_of - timedelta(days=1),
            valid_from=valid_from,
            valid_to=valid_to,
        )
    )

    rows = store.query_observations_as_of("ACME", as_of)
    expected = valid_from <= as_of < valid_to

    assert bool(rows) is expected
