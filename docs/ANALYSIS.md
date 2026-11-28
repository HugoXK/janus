# Analysis

The analysis layer is deterministic and point-in-time. Every feature is computed
from data known at `as_of`, and every materialized vector carries a hash.

## Indicator engine (v1)

`core/janus/analysis/indicators.py` owns the deterministic primitives:

| Indicator | Parameters | Warmup | NaN policy |
| --- | --- | --- | --- |
| SMA | window | window | leading NaN |
| EMA | span | 1 | from first |
| RSI | window | window | neutral 50 |
| MACD | fast/slow/signal | slow | from first |
| ATR | window | window | leading NaN |
| Bollinger | window/num_std | window | leading NaN |
| OBV | none | 1 | from first |
| VWAP | window or cumulative | 1 | leading NaN |
| ROC | window | window | leading NaN |
| Relative strength | benchmark | 1 | leading NaN |

`INDICATOR_SPECS` records each warmup/NaN contract. `indicator_version(name,
**params)` hashes the resolved parameters, so changing a window or a smoothing
constant produces a new identifier instead of silently reusing the old one.
Indicators are causal: a future row cannot change a historical value, and a
test computes each indicator on a prefix to prove it.

## Feature registry (v1)

| Feature | Definition | Notes |
| --- | --- | --- |
| `close` | Latest close | Raw price |
| `return_1d` / `5d` / `21d` | Simple returns | No lookahead |
| `rsi_14` | Wilder RSI(14) | Bounded 0–100 |
| `macd_hist` | MACD histogram | 12/26/9 default |
| `atr_14_pct` | ATR(14) / close | Volatility, scale-free |
| `bb_width_20` | Bollinger width(20) / mid | Volatility regime |
| `obv_slope_20` | 20-day change in OBV | Volume confirmation |
| `relative_strength_63` | Asset vs benchmark, normalized | Optional benchmark |
| `breadth` | Share of names above long MA | Optional breadth series |

The registry lives in `core/janus/analysis/features.py`. A new feature should add
a `FeatureSpec`, a test, and a version bump if the meaning changes.

## Feature store

`core/janus/analysis/feature_store.py` materializes a feature dict:

```python
feature_store.materialize("AAPL", as_of, features, version="v1", source_hash=...)
feature_store.get("AAPL", as_of, names=["rsi_14"])
feature_store.history("AAPL", "rsi_14")
```

- `as_of` must be timezone-aware.
- `get` returns the latest materialization at or before the requested time.
- `features_hash` is a SHA-256 of the canonical JSON feature vector.
- `source_hash` links the vector to the input snapshot.
- Re-materializing the same `(entity_id, as_of, version)` with a different hash
  raises `FeatureConflict`. A real revision must use a new version or pass
  `allow_revision=True` explicitly.

## Dashboard contracts

`core/janus/analysis/dashboards.py` defines:

- `MarketDashboard`: regime, breadth, volatility, indices, `features_hash`.
- `SectorRow` / `SectorDashboard`: relative return, RS ratio, RS momentum,
  quadrant, breadth.
- `StockDashboard`: close, feature dict, `features_hash`.

These models are part of `CONTRACT_MODELS` and the exported JSON Schema.

## Regime baseline

`classify_regime` is a rule-based baseline:

| Condition | Label |
| --- | --- |
| annualized vol ≥ 35% | `high-vol` |
| trend ≥ 3% and breadth ≥ 55% | `risk-on` |
| trend ≤ -3% and breadth ≤ 45% | `risk-off` |
| otherwise | `range` |

A learned HMM or change-point model can replace the classifier without changing
the dashboard contract. The rule-based version is auditable and cheap.

## Sector rotation

`rrg_coordinates` is a **simplified** Relative Rotation Graph: RS ratio and RS
momentum are normalized around 100, and the four quadrants are preserved
(leading, weakening, lagging, improving). The exact JdK smoothing is not
implemented; the API and tests make that explicit.

## Tests

- `tests/test_breadth.py` — advances/declines, new highs/lows, McClellan, TRIN.
- `tests/test_regime.py` — volatility, trend, regime labels.
- `tests/test_sector.py` — relative returns, RRG quadrants, breadth.
- `tests/test_features.py` — feature vector, hash, point-in-time store.
- `tests/test_dashboards.py` — dashboard models and contract registration.
