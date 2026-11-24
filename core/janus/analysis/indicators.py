from __future__ import annotations

import numpy as np
import pandas as pd


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
