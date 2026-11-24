from __future__ import annotations

import pandas as pd
import pytest

from janus.analysis.indicators import bollinger, macd, obv, rsi, sma


def test_sma_last_value() -> None:
    series = pd.Series([1, 2, 3, 4, 5], dtype=float)
    assert sma(series, 2).iloc[-1] == pytest.approx(4.5)


def test_rsi_is_bounded_and_high_in_an_uptrend() -> None:
    close = pd.Series(range(1, 40), dtype=float)
    values = rsi(close, 14).dropna()
    assert values.between(0, 100).all()
    assert values.iloc[-1] > 70


def test_rsi_is_neutral_on_flat_prices() -> None:
    close = pd.Series([100.0] * 40)
    values = rsi(close, 14)
    assert values.iloc[-1] == pytest.approx(50.0)


def test_macd_columns() -> None:
    close = pd.Series(range(1, 60), dtype=float)
    frame = macd(close)
    assert list(frame.columns) == ["macd", "signal", "hist"]


def test_bollinger_columns() -> None:
    close = pd.Series(range(1, 40), dtype=float)
    frame = bollinger(close)
    assert list(frame.columns) == ["mid", "upper", "lower"]
    assert frame["upper"].iloc[-1] > frame["mid"].iloc[-1] > frame["lower"].iloc[-1]


def test_obv_direction() -> None:
    close = pd.Series([1.0, 2.0, 1.0])
    volume = pd.Series([10, 10, 10])
    assert list(obv(close, volume)) == [0, 10, 0]
