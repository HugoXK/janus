from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from janus.data.base import DataUnavailable
from janus.data.tiingo import TiingoSource
from janus.memory.models import ObservationKind
from janus.memory.store import JanusStore

ROWS = [
    {
        "date": "2026-01-02T00:00:00.000Z",
        "open": 99.0,
        "high": 102.0,
        "low": 98.0,
        "close": 100.0,
        "volume": 1000.0,
        "adjOpen": 98.0,
        "adjHigh": 101.0,
        "adjLow": 97.0,
        "adjClose": 99.0,
        "adjVolume": 900.0,
        "divCash": 0.0,
        "splitFactor": 1.0,
    },
    {
        "date": "2026-01-03T00:00:00.000Z",
        "open": 100.0,
        "high": 103.0,
        "low": 99.0,
        "close": 101.0,
        "volume": 1100.0,
        "adjOpen": 99.0,
        "adjHigh": 102.0,
        "adjLow": 98.0,
        "adjClose": 100.0,
        "adjVolume": 1000.0,
        "divCash": 0.0,
        "splitFactor": 1.0,
    },
]


def _handler(request: httpx.Request) -> httpx.Response:
    assert request.headers["authorization"] == "Token test-key"
    assert "/tiingo/daily/AAPL/prices" in str(request.url)
    return httpx.Response(200, json=ROWS)


def _source() -> TiingoSource:
    client = httpx.Client(transport=httpx.MockTransport(_handler))
    return TiingoSource(api_key="test-key", client=client)


def test_fetch_maps_rows_and_keeps_adjusted_prices() -> None:
    source = _source()
    rows = source.fetch(
        "AAPL",
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 4, tzinfo=timezone.utc),
    )

    assert len(rows) == 2
    first = rows[0]
    assert first.id == "tiingo:price:AAPL:2026-01-02"
    assert first.kind is ObservationKind.price
    assert first.source == "tiingo"
    assert first.value["close"] == 100.0
    assert first.value["adjClose"] == 99.0
    assert first.value["splitFactor"] == 1.0
    assert first.published_at.hour == 23
    assert first.snapshot_id is None


def test_reingestion_is_idempotent() -> None:
    source = _source()
    rows = source.fetch(
        "AAPL",
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 4, tzinfo=timezone.utc),
    )
    store = JanusStore(":memory:")
    for row in rows:
        store.insert_observation(row)
    for row in rows:
        store.insert_observation(row)

    as_of = datetime(2026, 1, 5, tzinfo=timezone.utc)
    assert len(store.query_observations_as_of("AAPL", as_of)) == 2


def test_missing_key_is_explicit() -> None:
    source = TiingoSource(
        api_key=None,
        client=httpx.Client(transport=httpx.MockTransport(_handler)),
    )
    with pytest.raises(DataUnavailable, match="TIINGO_API_KEY"):
        source.fetch(
            "AAPL",
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 4, tzinfo=timezone.utc),
        )
