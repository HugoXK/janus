from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from janus.analysis.dashboards import (
    build_market_dashboard,
    build_sector_dashboard,
    build_stock_dashboard,
)
from janus.contracts import CONTRACT_MODELS


def test_market_dashboard_round_trip() -> None:
    as_of = datetime(2026, 1, 1, tzinfo=timezone.utc)
    dashboard = build_market_dashboard(
        as_of=as_of,
        regime="risk-on",
        breadth={"percent_above_ma": 0.6, "mcclellan": 12.0},
        volatility={"volatility": 0.2, "percentile": 0.4},
        indices={"SPX": 5000.0, "NDX": 18000.0},
        features_hash="abc123",
    )

    assert dashboard.regime == "risk-on"
    assert "risk-on" in dashboard.model_dump_json()
    assert dashboard.as_of == as_of


def test_sector_dashboard_rows() -> None:
    as_of = datetime(2026, 1, 1, tzinfo=timezone.utc)
    sectors = pd.DataFrame(
        {
            "relative_return_63d": [0.1, -0.1],
            "rs_ratio": [105.0, 95.0],
            "rs_momentum": [102.0, 98.0],
            "quadrant": ["leading", "lagging"],
            "breadth": [0.7, 0.3],
        },
        index=["Technology", "Energy"],
    )
    dashboard = build_sector_dashboard(
        as_of=as_of, benchmark="SPX", sectors=sectors, features_hash="abc123"
    )

    assert dashboard.benchmark == "SPX"
    assert [row.sector for row in dashboard.sectors] == ["Technology", "Energy"]
    assert dashboard.sectors[0].quadrant == "leading"


def test_stock_dashboard_and_contract_schema() -> None:
    as_of = datetime(2026, 1, 1, tzinfo=timezone.utc)
    dashboard = build_stock_dashboard(
        as_of=as_of,
        entity_id="AAPL",
        close=200.0,
        features={"rsi_14": 58.0, "feature_version": "v1"},
        features_hash="abc123",
    )

    assert dashboard.entity_id == "AAPL"
    assert dashboard.features["rsi_14"] == 58.0
    for name in ("MarketDashboard", "SectorRow", "SectorDashboard", "StockDashboard"):
        assert name in CONTRACT_MODELS
