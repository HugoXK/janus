from __future__ import annotations

import numpy as np
import pandas as pd


def advance_decline(advances: float, declines: float) -> float:
    if declines == 0:
        return float("inf") if advances > 0 else 1.0
    return advances / declines


def percent_above_ma(prices: pd.DataFrame, window: int = 200) -> pd.Series:
    ma = prices.rolling(window=window, min_periods=window).mean()
    return (prices > ma).mean(axis=1)


def new_highs_lows(prices: pd.DataFrame, window: int = 252) -> pd.DataFrame:
    highs = prices.rolling(window=window, min_periods=window).max()
    lows = prices.rolling(window=window, min_periods=window).min()
    new_highs = (prices >= highs).sum(axis=1)
    new_lows = (prices <= lows).sum(axis=1)
    return pd.DataFrame(
        {
            "new_highs": new_highs,
            "new_lows": new_lows,
            "net_new_highs": new_highs - new_lows,
        }
    )


def mcclellan_oscillator(
    prices: pd.DataFrame, short: int = 19, long: int = 39
) -> pd.Series:
    changes = prices.diff()
    net_advances = (changes > 0).sum(axis=1) - (changes < 0).sum(axis=1)
    fast = net_advances.ewm(span=short, adjust=False).mean()
    slow = net_advances.ewm(span=long, adjust=False).mean()
    return fast - slow


def trin(
    advances: float,
    declines: float,
    advancing_volume: float,
    declining_volume: float,
) -> float:
    if declines == 0 or declining_volume == 0:
        return float("nan")
    return (advances / declines) / (advancing_volume / declining_volume)


def breadth_summary(prices: pd.DataFrame, window: int = 200) -> dict[str, float]:
    above = percent_above_ma(prices, window)
    highs_lows = new_highs_lows(prices, window)
    mcclellan = mcclellan_oscillator(prices)

    def last(series: pd.Series, default: float = 0.0) -> float:
        return float(series.iloc[-1]) if len(series) else default

    return {
        "percent_above_ma": last(above, float("nan")),
        "new_highs": last(highs_lows["new_highs"]),
        "new_lows": last(highs_lows["new_lows"]),
        "net_new_highs": last(highs_lows["net_new_highs"]),
        "mcclellan": last(mcclellan, float("nan")),
    }


def breadth_series(prices: pd.DataFrame, window: int = 200) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "percent_above_ma": percent_above_ma(prices, window),
            "new_highs": new_highs_lows(prices, window)["new_highs"],
            "new_lows": new_highs_lows(prices, window)["new_lows"],
            "mcclellan": mcclellan_oscillator(prices),
        }
    )


def safe_ratio(numerator: float, denominator: float) -> float:
    if denominator == 0 or np.isnan(denominator):
        return float("nan")
    return numerator / denominator
