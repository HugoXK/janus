from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from janus.analysis.feature_store import FeatureConflict, FeatureStore
from janus.analysis.features import compute_features, features_hash
from janus.memory.store import JanusStore


def _prices() -> pd.DataFrame:
    index = pd.date_range("2025-01-01", periods=260, freq="D")
    close = pd.Series(np.linspace(100, 200, 260), index=index)
    return pd.DataFrame(
        {
            "close": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "volume": 1000.0,
        },
        index=index,
    )


def test_compute_features_is_deterministic_and_point_in_time() -> None:
    prices = _prices()
    benchmark = pd.Series(100.0, index=prices.index)
    breadth = pd.Series(0.7, index=prices.index)
    as_of = datetime(2025, 6, 1, tzinfo=timezone.utc)

    features = compute_features(
        prices, benchmark=benchmark, breadth=breadth, as_of=as_of
    )
    again = compute_features(
        prices, benchmark=benchmark, breadth=breadth, as_of=as_of
    )

    assert features == again
    assert features["feature_version"] == "v1"
    assert 0.0 <= features["rsi_14"] <= 100.0
    assert features["relative_strength_63"] > 1.0
    assert features["breadth"] == pytest.approx(0.7)
    expected_close = float(prices.loc[: pd.Timestamp("2025-06-01"), "close"].iloc[-1])
    assert features["close"] == pytest.approx(expected_close)


def test_future_prices_do_not_change_an_as_of_feature() -> None:
    prices = _prices()
    as_of = datetime(2025, 6, 1, tzinfo=timezone.utc)
    baseline = compute_features(prices, as_of=as_of)

    spiked = prices.copy()
    spiked.loc[pd.Timestamp("2025-09-01"), "close"] = 10_000.0
    after_spike = compute_features(spiked, as_of=as_of)

    assert baseline["close"] == after_spike["close"]


def test_zero_price_does_not_raise() -> None:
    prices = _prices()
    prices.loc[prices.index[-1], "close"] = 0.0
    features = compute_features(prices)
    assert features["atr_14_pct"] == 0.0


def test_feature_store_rejects_rewriting_history() -> None:
    store = JanusStore(":memory:")
    feature_store = FeatureStore(store)
    as_of = datetime(2026, 1, 1, tzinfo=timezone.utc)

    feature_store.materialize("ACME", as_of, {"close": 100.0})
    with pytest.raises(FeatureConflict):
        feature_store.materialize("ACME", as_of, {"close": 101.0})
    assert feature_store.get("ACME", as_of)["close"] == 100.0

    feature_store.materialize("ACME", as_of, {"close": 101.0}, allow_revision=True)
    assert feature_store.get("ACME", as_of)["close"] == 101.0


def test_features_hash_changes_with_values() -> None:
    first = {"close": 100.0, "rsi_14": 50.0}
    second = {"close": 101.0, "rsi_14": 50.0}
    assert features_hash(first) == features_hash(dict(first))
    assert features_hash(first) != features_hash(second)


def test_feature_store_is_point_in_time() -> None:
    store = JanusStore(":memory:")
    feature_store = FeatureStore(store)
    first = datetime(2026, 1, 1, tzinfo=timezone.utc)
    second = datetime(2026, 2, 1, tzinfo=timezone.utc)

    digest = feature_store.materialize(
        "ACME", first, {"close": 100.0, "rsi_14": 50.0}, source_hash="src-1"
    )
    assert digest == features_hash({"close": 100.0, "rsi_14": 50.0})
    assert feature_store.get("ACME", first) == {"close": 100.0, "rsi_14": 50.0}

    feature_store.materialize("ACME", second, {"close": 110.0, "rsi_14": 60.0})
    assert feature_store.get("ACME", first)["close"] == 100.0
    assert feature_store.get("ACME", second)["close"] == 110.0
    assert feature_store.get("ACME", second, names=["close"]) == {"close": 110.0}

    history = feature_store.history("ACME", "close")
    assert [row["value"] for row in history] == [110.0, 100.0]
