from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class IndicatorSpec:
    version: str
    warmup: int
    nan_policy: str
    params: dict[str, Any] = field(default_factory=dict)


INDICATOR_SPECS: dict[str, IndicatorSpec] = {
    "sma": IndicatorSpec("v1", 20, "leading_nan", {"window": 20}),
    "ema": IndicatorSpec("v1", 1, "from_first", {"span": 20}),
    "rsi": IndicatorSpec("v1", 14, "neutral_50", {"window": 14}),
    "macd": IndicatorSpec(
        "v1", 26, "from_first", {"fast": 12, "slow": 26, "signal": 9}
    ),
    "atr": IndicatorSpec("v1", 14, "leading_nan", {"window": 14}),
    "bollinger": IndicatorSpec(
        "v1", 20, "leading_nan", {"window": 20, "num_std": 2.0}
    ),
    "obv": IndicatorSpec("v1", 1, "from_first", {}),
    "vwap": IndicatorSpec("v1", 1, "leading_nan", {"window": None}),
    "relative_strength": IndicatorSpec("v1", 1, "leading_nan", {}),
    "roc": IndicatorSpec("v1", 10, "leading_nan", {"window": 10}),
}


def indicator_version(name: str, **params: Any) -> str:
    """Return a stable version id for one indicator parameterization."""

    if name not in INDICATOR_SPECS:
        raise KeyError(f"unknown indicator: {name}")
    spec = INDICATOR_SPECS[name]
    resolved = {**spec.params, **params}
    payload = json.dumps(resolved, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]
    return f"{name}-{spec.version}-{digest}"


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=window).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    """Wilder's Relative Strength Index.

    RSI is a feature, not a signal. Its meaning depends on the regime.
    """

    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    rs = avg_gain / avg_loss
    out = 100.0 - (100.0 / (1.0 + rs))
    return out.fillna(50.0)


def macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal)
    return pd.DataFrame(
        {
            "macd": macd_line,
            "signal": signal_line,
            "hist": macd_line - signal_line,
        }
    )


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    return pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)


def atr(
    high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14
) -> pd.Series:
    return true_range(high, low, close).ewm(
        alpha=1 / window, min_periods=window, adjust=False
    ).mean()


def bollinger(
    close: pd.Series, window: int = 20, num_std: float = 2.0
) -> pd.DataFrame:
    mid = sma(close, window)
    std = close.rolling(window=window, min_periods=window).std()
    return pd.DataFrame(
        {"mid": mid, "upper": mid + num_std * std, "lower": mid - num_std * std}
    )


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff()).fillna(0.0)
    return (direction * volume).cumsum()


def vwap(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    window: int | None = None,
) -> pd.Series:
    """Volume-weighted average price.

    ``window=None`` is a cumulative VWAP from the first row; a window gives a
    rolling VWAP. Rows with zero total volume return NaN.
    """

    typical = (high + low + close) / 3.0
    if window is None:
        numerator = (typical * volume).cumsum()
        denominator = volume.cumsum()
    else:
        numerator = (typical * volume).rolling(window=window, min_periods=window).sum()
        denominator = volume.rolling(window=window, min_periods=window).sum()
    return numerator / denominator.replace(0.0, np.nan)


def roc(close: pd.Series, window: int = 10) -> pd.Series:
    """Rate of change as a decimal return, not a percentage."""

    return close.pct_change(window)


def relative_strength(asset: pd.Series, benchmark: pd.Series) -> pd.Series:
    """Relative strength normalized to 1.0 at the first common observation."""

    aligned = pd.concat([asset, benchmark], axis=1).dropna()
    if aligned.empty:
        return pd.Series(dtype=float)
    a = aligned.iloc[:, 0] / aligned.iloc[0, 0]
    b = aligned.iloc[:, 1] / aligned.iloc[0, 1]
    return a / b


def zscore(series: pd.Series, window: int) -> pd.Series:
    mean = series.rolling(window=window, min_periods=window).mean()
    std = series.rolling(window=window, min_periods=window).std()
    return (series - mean) / std.replace(0.0, np.nan)


def percentile_rank(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=window).apply(
        lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False
    )
