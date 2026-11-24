from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import pandas as pd

from .indicators import atr, bollinger, macd, obv, relative_strength, rsi


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    version: str
    description: str


FEATURES: tuple[FeatureSpec, ...] = (
    FeatureSpec("close", "v1", "Latest close"),
    FeatureSpec("return_1d", "v1", "One-day return"),
    FeatureSpec("return_5d", "v1", "Five-day return"),
    FeatureSpec("return_21d", "v1", "Twenty-one day return"),
    FeatureSpec("rsi_14", "v1", "Wilder RSI(14)"),
    FeatureSpec("macd_hist", "v1", "MACD histogram"),
    FeatureSpec("atr_14_pct", "v1", "ATR(14) as a share of close"),
    FeatureSpec("bb_width_20", "v1", "Bollinger width(20)"),
    FeatureSpec("obv_slope_20", "v1", "20-day change in OBV"),
    FeatureSpec("relative_strength_63", "v1", "Relative strength vs benchmark"),
    FeatureSpec("breadth", "v1", "Share of names above their long moving average"),
)


def _as_of_stamp(as_of: Optional[datetime]) -> Optional[pd.Timestamp]:
    if as_of is None:
        return None
    stamp = pd.Timestamp(as_of)
    if stamp.tz is not None:
        stamp = stamp.tz_convert("UTC").tz_localize(None)
    return stamp


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(number) or math.isinf(number):
        return default
    return number


def _last(series: pd.Series, default: float = 0.0) -> float:
    if series.empty:
        return default
    return _finite(series.iloc[-1], default)


def compute_features(
    prices: pd.DataFrame,
    *,
    benchmark: Optional[pd.Series] = None,
    breadth: Optional[pd.Series] = None,
    as_of: Optional[datetime] = None,
) -> dict[str, Any]:
    """Compute a deterministic, point-in-time feature set.

    ``prices`` must have a DatetimeIndex and a ``close`` column; ``high``,
    ``low`` and ``volume`` are optional. The index is expected to be naive UTC
    dates or timestamps.
    """

    frame = prices.copy()
    stamp = _as_of_stamp(as_of)
    if stamp is not None:
        frame = frame.loc[frame.index <= stamp]
    if frame.empty:
        raise ValueError("no prices at or before as_of")
    if "close" not in frame.columns:
        raise ValueError("prices must include a 'close' column")

    close = frame["close"].astype(float)
    high = frame["high"].astype(float) if "high" in frame.columns else close
    low = frame["low"].astype(float) if "low" in frame.columns else close
    volume = (
        frame["volume"].astype(float)
        if "volume" in frame.columns
        else pd.Series(0.0, index=close.index)
    )

    last_close = _finite(close.iloc[-1], 0.0)
    macd_frame = macd(close)
    bands = bollinger(close)
    mid = _finite(bands["mid"].iloc[-1], 0.0) if len(bands) else 0.0
    width = (
        (_finite(bands["upper"].iloc[-1]) - _finite(bands["lower"].iloc[-1])) / mid
        if mid
        else 0.0
    )
    atr_value = _last(atr(high, low, close, 14), 0.0)

    features: dict[str, Any] = {
        "close": last_close,
        "return_1d": _finite(close.pct_change().iloc[-1]) if len(close) >= 2 else 0.0,
        "return_5d": _finite(close.pct_change(5).iloc[-1]) if len(close) >= 6 else 0.0,
        "return_21d": _finite(close.pct_change(21).iloc[-1]) if len(close) >= 22 else 0.0,
        "rsi_14": _last(rsi(close, 14), 50.0),
        "macd_hist": _last(macd_frame["hist"], 0.0),
        "atr_14_pct": (atr_value / last_close) if last_close else 0.0,
        "bb_width_20": _finite(width),
        "obv_slope_20": (
            _finite(obv(close, volume).diff(20).iloc[-1]) if len(close) >= 21 else 0.0
        ),
        "feature_version": "v1",
    }

    if benchmark is not None:
        bench = benchmark.reindex(close.index).ffill()
        if bench.notna().any():
            features["relative_strength_63"] = _last(
                relative_strength(close, bench), 1.0
            )
        else:
            features["relative_strength_63"] = 1.0

    if breadth is not None:
        breadth_aligned = breadth.reindex(close.index).ffill()
        features["breadth"] = _last(breadth_aligned, 0.5)

    return features


def features_hash(features: dict[str, Any]) -> str:
    payload = json.dumps(features, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
