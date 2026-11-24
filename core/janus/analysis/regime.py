from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd


def realized_volatility(
    close: pd.Series, window: int = 20, annualization: int = 252
) -> pd.Series:
    returns = close.pct_change()
    return returns.rolling(window=window, min_periods=window).std() * math.sqrt(
        annualization
    )


def trend_strength(close: pd.Series, short: int = 50, long: int = 200) -> pd.Series:
    short_ma = close.rolling(window=short, min_periods=short).mean()
    long_ma = close.rolling(window=long, min_periods=long).mean()
    return short_ma / long_ma - 1.0


def classify_regime(*, volatility: float, trend: float, breadth: float) -> str:
    """A deterministic baseline regime label.

    A learned HMM/change-point model can replace this later; the interface is the
    same, and the rule-based version is auditable.
    """

    if not all(map(math.isfinite, (volatility, trend, breadth))):
        return "unknown"
    if volatility >= 0.35:
        return "high-vol"
    if trend >= 0.03 and breadth >= 0.55:
        return "risk-on"
    if trend <= -0.03 and breadth <= 0.45:
        return "risk-off"
    return "range"


def regime_features(
    close: pd.Series,
    breadth: Optional[pd.Series] = None,
    window: int = 20,
) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "volatility": realized_volatility(close, window),
            "trend": trend_strength(close),
        }
    )
    if breadth is None:
        frame["breadth"] = 0.5
    else:
        frame["breadth"] = breadth.reindex(close.index).ffill().fillna(0.5)
    frame["regime"] = [
        classify_regime(
            volatility=float(vol) if math.isfinite(float(vol)) else float("nan"),
            trend=float(trend) if math.isfinite(float(trend)) else float("nan"),
            breadth=float(br) if math.isfinite(float(br)) else float("nan"),
        )
        for vol, trend, br in zip(
            frame["volatility"], frame["trend"], frame["breadth"]
        )
    ]
    return frame


def volatility_percentile(close: pd.Series, window: int = 20, lookback: int = 252) -> float:
    volatility = realized_volatility(close, window).dropna()
    if volatility.empty:
        return float("nan")
    window_values = volatility.tail(lookback)
    return float((window_values <= window_values.iloc[-1]).mean())


def latest_regime(
    close: pd.Series, breadth: Optional[pd.Series] = None
) -> dict[str, float | str]:
    frame = regime_features(close, breadth)
    latest = frame.dropna(subset=["volatility", "trend"]).tail(1)
    if latest.empty:
        return {
            "regime": "unknown",
            "volatility": float("nan"),
            "trend": float("nan"),
            "breadth": 0.5,
            "volatility_percentile": float("nan"),
        }
    row = latest.iloc[0]
    return {
        "regime": str(row["regime"]),
        "volatility": float(row["volatility"]),
        "trend": float(row["trend"]),
        "breadth": float(row["breadth"]),
        "volatility_percentile": volatility_percentile(close),
    }


def trend_score(close: pd.Series) -> float:
    values = trend_strength(close).dropna()
    if values.empty:
        return float("nan")
    return float(np.tanh(values.iloc[-1] * 20.0))
