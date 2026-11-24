from __future__ import annotations

import math
from datetime import datetime
from typing import Any

import pandas as pd

from ..memory.models import UtcModel


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(number) or math.isinf(number):
        return default
    return number


class MarketDashboard(UtcModel):
    as_of: datetime
    regime: str
    breadth: dict[str, float]
    volatility: dict[str, float]
    indices: dict[str, float]
    features_hash: str


class SectorRow(UtcModel):
    sector: str
    relative_return_63d: float
    rs_ratio: float
    rs_momentum: float
    quadrant: str
    breadth: float


class SectorDashboard(UtcModel):
    as_of: datetime
    benchmark: str
    sectors: list[SectorRow]
    features_hash: str


class StockDashboard(UtcModel):
    as_of: datetime
    entity_id: str
    close: float
    features: dict[str, Any]
    features_hash: str


def build_market_dashboard(
    *,
    as_of: datetime,
    regime: str,
    breadth: dict[str, float],
    volatility: dict[str, float],
    indices: dict[str, float],
    features_hash: str,
) -> MarketDashboard:
    return MarketDashboard(
        as_of=as_of,
        regime=regime,
        breadth={key: _finite(value) for key, value in breadth.items()},
        volatility={key: _finite(value) for key, value in volatility.items()},
        indices={key: _finite(value) for key, value in indices.items()},
        features_hash=features_hash,
    )


def build_sector_dashboard(
    *,
    as_of: datetime,
    benchmark: str,
    sectors: pd.DataFrame,
    features_hash: str,
) -> SectorDashboard:
    rows = []
    for sector, row in sectors.iterrows():
        rows.append(
            SectorRow(
                sector=str(sector),
                relative_return_63d=_finite(row.get("relative_return_63d")),
                rs_ratio=_finite(row.get("rs_ratio"), 100.0),
                rs_momentum=_finite(row.get("rs_momentum"), 100.0),
                quadrant=str(row.get("quadrant", "neutral")),
                breadth=_finite(row.get("breadth")),
            )
        )
    return SectorDashboard(
        as_of=as_of,
        benchmark=benchmark,
        sectors=rows,
        features_hash=features_hash,
    )


def build_stock_dashboard(
    *,
    as_of: datetime,
    entity_id: str,
    close: float,
    features: dict[str, Any],
    features_hash: str,
) -> StockDashboard:
    return StockDashboard(
        as_of=as_of,
        entity_id=entity_id,
        close=_finite(close),
        features=features,
        features_hash=features_hash,
    )
