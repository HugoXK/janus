from __future__ import annotations

import numpy as np
import pandas as pd


def relative_returns(
    sector_prices: pd.DataFrame,
    benchmark: pd.Series,
    window: int = 63,
) -> pd.DataFrame:
    """Relative return per sector over ``window`` days.

    Returns a time-indexed DataFrame with one column per sector.
    """

    sectors = sector_prices
    bench = benchmark.reindex(sectors.index).ffill()
    sector_return = sectors / sectors.shift(window) - 1.0
    bench_return = bench / bench.shift(window) - 1.0
    return sector_return.sub(bench_return, axis=0)


def classify_quadrant(rs_ratio: float, rs_momentum: float) -> str:
    if not (np.isfinite(rs_ratio) and np.isfinite(rs_momentum)):
        return "neutral"
    if rs_ratio >= 100.0 and rs_momentum >= 100.0:
        return "leading"
    if rs_ratio < 100.0 and rs_momentum >= 100.0:
        return "weakening"
    if rs_ratio < 100.0 and rs_momentum < 100.0:
        return "lagging"
    return "improving"


def rrg_coordinates(
    sector_prices: pd.DataFrame,
    benchmark: pd.Series,
    window: int = 63,
    momentum_window: int = 21,
) -> pd.DataFrame:
    """A simplified Relative Rotation Graph.

    ``rs_ratio`` and ``rs_momentum`` are normalized around 100. The exact JdK
    smoothing is intentionally omitted; the quadrant semantics are preserved.
    """

    sectors = sector_prices
    bench = benchmark.reindex(sectors.index).ffill()
    rs = sectors.div(bench, axis=0)
    rolling_mean = rs.rolling(window=window, min_periods=window).mean()
    rs_ratio = 100.0 * rs.div(rolling_mean)
    rs_momentum = 100.0 * rs_ratio.div(rs_ratio.shift(momentum_window))

    latest_ratio = rs_ratio.iloc[-1] if len(rs_ratio) else pd.Series(dtype=float)
    latest_momentum = rs_momentum.iloc[-1] if len(rs_momentum) else pd.Series(dtype=float)
    rows = []
    for sector in sectors.columns:
        ratio = float(latest_ratio.get(sector, float("nan")))
        momentum = float(latest_momentum.get(sector, float("nan")))
        rows.append(
            {
                "sector": sector,
                "rs_ratio": ratio,
                "rs_momentum": momentum,
                "quadrant": classify_quadrant(ratio, momentum),
            }
        )
    return pd.DataFrame(rows).set_index("sector")


def sector_breadth(prices: pd.DataFrame, window: int = 50) -> pd.Series:
    ma = prices.rolling(window=window, min_periods=window).mean()
    latest = (prices > ma).iloc[-1] if len(prices) else pd.Series(dtype=float)
    return latest.astype(float)


def sector_snapshot(
    sector_prices: pd.DataFrame,
    benchmark: pd.Series,
    window: int = 63,
    breadth_window: int = 50,
) -> pd.DataFrame:
    rrg = rrg_coordinates(sector_prices, benchmark, window=window)
    returns = relative_returns(sector_prices, benchmark, window=63)
    latest_returns = returns.iloc[-1].rename("relative_return_63d") if len(returns) else None
    breadth = sector_breadth(sector_prices, breadth_window)
    frame = rrg.join(breadth.rename("breadth"))
    if latest_returns is not None:
        frame = frame.join(latest_returns)
    else:
        frame["relative_return_63d"] = 0.0
    return frame.fillna(
        {
            "rs_ratio": 100.0,
            "rs_momentum": 100.0,
            "relative_return_63d": 0.0,
            "breadth": 0.0,
        }
    )
