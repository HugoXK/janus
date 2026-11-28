from __future__ import annotations

import pandas as pd
import pytest

from janus.analysis.indicators import (
    INDICATOR_SPECS,
    atr,
    bollinger,
    indicator_version,
    macd,
    obv,
    roc,
    rsi,
    sma,
    vwap,
)


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


def test_vwap_reference_values() -> None:
    high = pd.Series([11.0, 12.0, 13.0])
    low = pd.Series([9.0, 10.0, 11.0])
    close = pd.Series([10.0, 11.0, 12.0])
    volume = pd.Series([1.0, 2.0, 1.0])

    cumulative = vwap(high, low, close, volume)
    assert cumulative.iloc[-1] == pytest.approx(11.0)
    rolling = vwap(high, low, close, volume, window=2)
    assert rolling.iloc[-1] == pytest.approx((11.0 * 2 + 12.0) / 3)


def test_vwap_zero_volume_is_nan() -> None:
    series = pd.Series([10.0, 11.0])
    volumes = pd.Series([0.0, 0.0])
    assert vwap(series, series, series, volumes).isna().all()


def test_roc_is_a_decimal_return() -> None:
    close = pd.Series([100.0, 110.0, 121.0])
    assert roc(close, 1).iloc[-1] == pytest.approx(0.1)


def test_indicator_versions_change_with_parameters() -> None:
    assert indicator_version("rsi") == indicator_version("rsi", window=14)
    assert indicator_version("rsi", window=21) != indicator_version("rsi")


def test_indicator_specs_document_warmup_and_nan_policy() -> None:
    assert INDICATOR_SPECS["rsi"].warmup == 14
    assert INDICATOR_SPECS["rsi"].nan_policy == "neutral_50"
    assert INDICATOR_SPECS["vwap"].params["window"] is None
    with pytest.raises(KeyError, match="unknown indicator"):
        indicator_version("not-an-indicator")


def test_future_rows_do_not_change_historical_values() -> None:
    index = pd.date_range("2026-01-01", periods=80)
    close = pd.Series([100.0 + value for value in range(80)], index=index)
    high = close + 2.0
    low = close - 2.0
    volume = pd.Series([1000.0 + value for value in range(80)], index=index)
    cutoff = 50

    checks = [
        (rsi(close, 14), rsi(close.iloc[:cutoff], 14)),
        (macd(close)["hist"], macd(close.iloc[:cutoff])["hist"]),
        (atr(high, low, close, 14), atr(high.iloc[:cutoff], low.iloc[:cutoff], close.iloc[:cutoff], 14)),
        (bollinger(close)["mid"], bollinger(close.iloc[:cutoff])["mid"]),
        (obv(close, volume), obv(close.iloc[:cutoff], volume.iloc[:cutoff])),
        (
            vwap(high, low, close, volume),
            vwap(high.iloc[:cutoff], low.iloc[:cutoff], close.iloc[:cutoff], volume.iloc[:cutoff]),
        ),
    ]
    for full, prefix in checks:
        pd.testing.assert_series_equal(full.iloc[:cutoff], prefix)
