from __future__ import annotations

import numpy as np
import pandas as pd

from janus.analysis.regime import (
    classify_regime,
    latest_regime,
    realized_volatility,
    regime_features,
    trend_strength,
    volatility_percentile,
)


def _uptrend() -> pd.Series:
    index = pd.date_range("2025-01-01", periods=300, freq="D")
    return pd.Series(np.linspace(100, 200, 300), index=index)


def test_classify_regime() -> None:
    assert classify_regime(volatility=0.20, trend=0.05, breadth=0.70) == "risk-on"
    assert classify_regime(volatility=0.20, trend=-0.05, breadth=0.30) == "risk-off"
    assert classify_regime(volatility=0.50, trend=0.10, breadth=0.80) == "high-vol"
    assert classify_regime(volatility=0.20, trend=0.00, breadth=0.50) == "range"
    assert classify_regime(volatility=float("nan"), trend=0.0, breadth=0.5) == "unknown"


def test_realized_volatility_and_trend_strength() -> None:
    close = _uptrend()
    volatility = realized_volatility(close, window=20)
    trend = trend_strength(close)

    assert float(volatility.dropna().iloc[-1]) >= 0.0
    assert float(trend.dropna().iloc[-1]) > 0.0


def test_regime_features_and_latest_regime() -> None:
    close = _uptrend()
    breadth = pd.Series(0.8, index=close.index)
    frame = regime_features(close, breadth)
    latest = latest_regime(close, breadth)

    assert len(frame) == len(close)
    assert set(frame.columns) == {"volatility", "trend", "breadth", "regime"}
    assert latest["regime"] == "risk-on"
    assert 0.0 <= volatility_percentile(close) <= 1.0
