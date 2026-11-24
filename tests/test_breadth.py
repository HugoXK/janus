from __future__ import annotations

import numpy as np
import pandas as pd

from janus.analysis.breadth import (
    advance_decline,
    breadth_summary,
    mcclellan_oscillator,
    new_highs_lows,
    percent_above_ma,
    trin,
)


def _prices() -> pd.DataFrame:
    index = pd.date_range("2025-01-01", periods=300, freq="D")
    return pd.DataFrame(
        {
            "A": np.linspace(100, 200, 300),
            "B": np.linspace(90, 180, 300),
            "C": np.linspace(80, 160, 300),
        },
        index=index,
    )


def test_breadth_summary_on_an_uptrend() -> None:
    summary = breadth_summary(_prices(), window=200)

    assert summary["percent_above_ma"] == 1.0
    assert summary["new_highs"] == 3.0
    assert summary["new_lows"] == 0.0
    assert summary["net_new_highs"] == 3.0
    assert summary["mcclellan"] > 0.0


def test_advance_decline_and_trin() -> None:
    assert advance_decline(3, 1) == 3.0
    assert advance_decline(0, 0) == 1.0
    assert trin(3, 1, 300, 100) == 1.0


def test_new_highs_lows_and_percent_above_ma() -> None:
    prices = _prices()
    highs_lows = new_highs_lows(prices, window=100)
    above = percent_above_ma(prices, window=100)

    assert highs_lows.iloc[-1]["new_highs"] == 3
    assert highs_lows.iloc[-1]["new_lows"] == 0
    assert 0.0 <= float(above.iloc[-1]) <= 1.0


def test_mcclellan_is_positive_when_more_names_advance() -> None:
    prices = _prices()
    values = mcclellan_oscillator(prices)
    assert float(values.iloc[-1]) > 0.0
