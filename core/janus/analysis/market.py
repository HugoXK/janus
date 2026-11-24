from __future__ import annotations

import pandas as pd


def advance_decline(advances: float, declines: float) -> float:
    """Advance/decline ratio. Above 1 means more winners than losers."""

    if declines == 0:
        return float("inf") if advances > 0 else 1.0
    return advances / declines


def percent_above_ma(prices: pd.DataFrame, window: int = 200) -> pd.Series:
    """Share of columns trading above their own moving average."""

    ma = prices.rolling(window=window, min_periods=window).mean()
    return (prices > ma).mean(axis=1)


def breadth_thrust(percent_above: pd.Series, window: int = 10) -> pd.Series:
    """Change in breadth over a short window; useful for regime detection."""

    return percent_above - percent_above.shift(window)


def regime_label(
    trend: float,
    volatility: float,
    breadth: float,
) -> str:
    """A deliberately simple regime label for the V1 dashboard.

    ``trend`` and ``breadth`` are in [0, 1]; ``volatility`` is annualized.
    This is a placeholder for a proper HMM/change-point model.
    """

    if volatility >= 0.35:
        return "high-vol"
    if trend >= 0.6 and breadth >= 0.55:
        return "risk-on"
    if trend <= 0.4 and breadth <= 0.45:
        return "risk-off"
    return "range"


def relative_rotation(asset_momentum: float, benchmark_momentum: float) -> tuple[float, float]:
    """A minimal RRG-style coordinate: (relative strength, relative momentum)."""

    return asset_momentum - benchmark_momentum, asset_momentum - benchmark_momentum
