from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from janus.data.yfinance_source import YFinanceSource
from janus.memory.models import ObservationKind


def _frame() -> pd.DataFrame:
    index = pd.to_datetime(["2026-01-02", "2026-01-03"])
    return pd.DataFrame(
        {
            "Open": [99.0, 100.0],
            "High": [102.0, 103.0],
            "Low": [98.0, 99.0],
            "Close": [100.0, 101.0],
            "Adj Close": [99.0, 100.0],
            "Volume": [1000.0, 1100.0],
        },
        index=index,
    )


def test_yfinance_maps_frame_and_adjusted_close() -> None:
    source = YFinanceSource(history_fetcher=lambda ticker, start, end: _frame())
    rows = source.fetch(
        "AAPL",
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 4, tzinfo=timezone.utc),
    )

    assert len(rows) == 2
    first = rows[0]
    assert first.id == "yfinance:price:AAPL:2026-01-02"
    assert first.kind is ObservationKind.price
    assert first.source == "yfinance"
    assert first.value["close"] == 100.0
    assert first.value["adj_close"] == 99.0
    assert first.confidence == 0.7
    assert first.published_at.hour == 23


def test_empty_frame_returns_nothing() -> None:
    source = YFinanceSource(history_fetcher=lambda ticker, start, end: pd.DataFrame())
    rows = source.fetch(
        "AAPL",
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 4, tzinfo=timezone.utc),
    )
    assert rows == []
