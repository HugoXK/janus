from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from janus.forecast.backtest import (
    LeakDetected,
    WalkForwardBacktester,
    WalkForwardSplitter,
)
from janus.forecast.baseline import LogisticDirectionModel


def _data(n: int = 240):
    rng = np.random.default_rng(21)
    features = np.column_stack(
        [
            rng.uniform(0, 100, n),
            rng.uniform(-1, 1, n),
            rng.uniform(0, 1, n),
        ]
    )
    score = (features[:, 1] * 0.8 + (features[:, 2] - 0.5) * 0.5)
    outcomes = (score > 0).astype(float)
    returns = np.where(outcomes > 0, 0.004, -0.003) + rng.normal(0, 0.002, n)
    return features, outcomes, returns


def test_splitter_respects_purge_and_embargo() -> None:
    folds = WalkForwardSplitter(
        200, train_size=80, test_size=20, purge=5, embargo=3
    ).split()
    assert folds
    for fold in folds:
        assert fold.train_end == fold.test_start - 5
        assert fold.train_end - fold.train_start == 80
        assert fold.test_end - fold.test_start == 20
    for previous, current in zip(folds, folds[1:]):
        assert current.test_start - previous.test_end >= 3


def test_backtest_is_deterministic_and_reports_costs() -> None:
    features, outcomes, returns = _data()
    backtester = WalkForwardBacktester(
        lambda: LogisticDirectionModel(epochs=150),
        train_size=80,
        test_size=40,
        purge=2,
        embargo=1,
        costs_bps=10,
    )
    first = backtester.run(features, outcomes, returns=returns).to_dict()
    second = backtester.run(features, outcomes, returns=returns).to_dict()

    assert first == second
    assert first["costs_bps"] == 10
    assert first["folds"]
    assert first["net_return"] is not None
    assert first["gross_return"] is not None
    assert first["net_return"] <= first["gross_return"]
    assert all(fold["turnover"] is not None for fold in first["folds"])


def test_backtest_without_returns_has_no_pnl() -> None:
    features, outcomes, _ = _data()
    report = WalkForwardBacktester(
        lambda: LogisticDirectionModel(epochs=50),
        train_size=100,
        test_size=40,
    ).run(features, outcomes)
    assert report.gross_return is None
    assert report.net_return is None


def test_non_monotonic_timestamps_are_a_leak() -> None:
    features, outcomes, _ = _data(200)
    stamps = [datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=i) for i in range(200)]
    stamps[50] = stamps[49]
    backtester = WalkForwardBacktester(
        lambda: LogisticDirectionModel(epochs=50),
        train_size=80,
        test_size=20,
    )
    with pytest.raises(LeakDetected, match="strictly increasing"):
        backtester.run(features, outcomes, timestamps=stamps)


def test_splitter_rejects_impossible_windows() -> None:
    with pytest.raises(ValueError, match="positive"):
        WalkForwardSplitter(10, train_size=0, test_size=2)
    with pytest.raises(ValueError, match="not enough"):
        WalkForwardSplitter(10, train_size=8, test_size=5)
