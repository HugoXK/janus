from __future__ import annotations

import numpy as np
import pandas as pd

from janus.analysis.sector import (
    classify_quadrant,
    relative_returns,
    rrg_coordinates,
    sector_breadth,
    sector_snapshot,
)


def _sector_prices() -> tuple[pd.DataFrame, pd.Series]:
    index = pd.date_range("2025-01-01", periods=220, freq="D")
    bench = pd.Series(100.0 * (1.005 ** np.arange(220)), index=index)
    first = np.where(np.arange(220) < 160, 0.005, 0.015)
    second = np.where(np.arange(220) < 160, 0.005, -0.005)
    accelerating = pd.Series(100.0 * np.cumprod(1 + first), index=index)
    decelerating = pd.Series(100.0 * np.cumprod(1 + second), index=index)
    prices = pd.DataFrame(
        {"Accelerating": accelerating, "Decelerating": decelerating, "Benchmark": bench}
    )
    return prices, bench


def test_relative_returns_columns_and_direction() -> None:
    prices, bench = _sector_prices()
    returns = relative_returns(prices, bench, window=63)

    assert list(returns.columns) == ["Accelerating", "Decelerating", "Benchmark"]
    assert returns.iloc[-1]["Accelerating"] > 0
    assert returns.iloc[-1]["Decelerating"] < 0


def test_classify_quadrant() -> None:
    assert classify_quadrant(101, 101) == "leading"
    assert classify_quadrant(99, 101) == "weakening"
    assert classify_quadrant(99, 99) == "lagging"
    assert classify_quadrant(101, 99) == "improving"
    assert classify_quadrant(float("nan"), 99) == "neutral"


def test_rrg_and_snapshot() -> None:
    prices, bench = _sector_prices()
    rrg = rrg_coordinates(prices, bench)
    snapshot = sector_snapshot(prices, bench)
    breadth = sector_breadth(prices, window=50)

    assert set(rrg.columns) == {"rs_ratio", "rs_momentum", "quadrant"}
    assert rrg.loc["Accelerating", "rs_ratio"] > rrg.loc["Decelerating", "rs_ratio"]
    assert snapshot.shape[0] == 3
    assert snapshot["breadth"].between(0.0, 1.0).all()
    assert breadth.between(0.0, 1.0).all()
