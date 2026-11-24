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
