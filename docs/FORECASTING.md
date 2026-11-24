# Forecasting

Janus forecasts **probabilities and scenarios**, not prices.

## Forecast types

- Direction probability over a horizon (1D, 1W, 1M, 3M).
- Return quantiles.
- Regime probability (risk-on, range, risk-off, high-vol).
- Event probability (earnings beat, drawdown risk, guidance cut).
- Scenario tree with explicit assumptions and falsifiers.

## Feature families

| Family | Examples |
| --- | --- |
| Trend | MA/EMA distance, MACD, ADX |
| Momentum | RSI, ROC, relative strength |
| Volatility | ATR, Bollinger width, realized vol |
| Volume | OBV, VWAP, volume profile |
| Breadth | % above 50/200 DMA, advance/decline, new highs/lows |
| Fundamentals | valuation, growth, margins, revisions |
| Macro | rates, curve, credit spreads, dollar, commodities |
| Sentiment | news, social, put/call, skew, short interest |
| Flows | ETF flows, institutional positioning |

## The right way to use RSI

RSI is a feature, not a signal.

- Condition on the regime: oversold in an uptrend is different from oversold in
  a downtrend.
- Normalize with percentiles or z-scores; do not compare raw RSI across assets.
- Combine with trend, volume, breadth, and fundamentals.
- Test parameter robustness; do not cherry-pick RSI(14).
- Backtest with walk-forward, costs, and multiple-testing corrections.
- Record the RSI value, regime, and forecast together so calibration can tell you
  whether RSI actually helped.

## Calibration

Every prediction is scored after the outcome:

- Brier score for binary events.
- Log loss for probabilistic forecasts.
- Reliability curve and expected calibration error.
- Quantile coverage for interval forecasts.

A forecast that is accurate but overconfident is not a good forecast.

## Baseline model

`LogisticDirectionModel` is a dependency-free logistic regression over
`rsi_14`, `trend`, and `breadth`. Features are standardized before fitting, the
model carries a `ModelCard`, and `to_dict` / `from_dict` include the
hyperparameters as well as the coefficients so a run is reproducible. It is a
baseline, not a trading strategy; there are no transaction costs and no claim of
alpha.

## Calibration service

`CalibrationService` fits Platt scaling or isotonic regression and reports:

- Brier, log loss, ECE, and a reliability curve;
- slices by regime, horizon, and persona when metadata is supplied;
- `from_store` over settled predictions, so the report is built from the ledger.
  It reads the horizon and the thesis's persona id; pass `regime_resolver` to
  add regime slices, or call `report` with explicit metadata.

## Settlement

`SettlementService` resolves a prediction through a resolver and writes the
outcome through the append-only ledger. The first resolver is
`DirectionOutcomeResolver`: it labels `up` / `down` / `flat` from a start/end
price pair and scores a P(up) forecast as 1 for `up`, 0 otherwise. It rejects a
prediction whose target is not `direction` or `up`, so the P(up) convention is
explicit. A settled prediction cannot be settled twice.

## Debrief and persona weighting

`AttributionEngine` decomposes an outcome into technical, fundamental, macro,
sentiment, and luck contributions and normalizes them to a share of 1.
`debrief_prediction` stores the attribution and lessons as a `Review`.

`PersonaPolicy` maps a taste profile to feature weights and ranks evidence by
category. Two personas can therefore read the same evidence differently; the
weights are stored with the `Persona` and are auditable.

## Anti-lookahead rules

1. Every query carries `as_of`.
2. Fundamentals use as-filed data, not restated data.
3. Macro uses ALFRED vintages when available.
4. Prices are adjusted consistently; corporate actions are explicit.
5. Backtests use delisted names where possible.
6. Predictions are written before outcomes and never edited.

## LLM role

LLMs extract evidence, write narratives, generate scenarios, and explain
counterfactuals. They do not compute indicators, size positions, or invent
prices. Deterministic code owns every number that can be checked.
