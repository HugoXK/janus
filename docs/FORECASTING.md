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

## Model registry

A forecast must be reproducible months later, so every fitted model can be
written as a content-addressed artifact. The registry is a local file store, not
a database table, and adding it required no migration.

- `ModelRegistry()` writes to `$JANUS_HOME/models/<artifact_id>.json` (default
  `~/.janus/models/`); `JANUS_HOME` redirects the store. Each file is canonical
  JSON (sorted keys, tight separators) written with an atomic replace.
- `artifact_id` is the SHA-256 of the canonical JSON of the model card,
  parameters, feature values and hash, data snapshot, code version, and artifact
  version. `created_at` is excluded, so saving identical content is idempotent
  and the id stays stable.
- `save(model, features=..., data_snapshot=..., code_version=...)` records the
  fitted parameters and card, computes `features_hash` with
  `janus.analysis.features.features_hash`, and defaults `version` to the model
  card's version.
- `load(ref)` accepts a full 64-hex id, a unique id prefix of at least four
  characters, or an exact version. A missing or ambiguous reference raises
  `ArtifactNotFoundError`; an ambiguous one names every candidate id. A file
  that is not valid JSON or no longer re-hashes to its name raises
  `ArtifactCorruptError`.
- `replay(ref, features=...)` rebuilds the model from the artifact and returns
  the same probability as `predict_one`; supplying a different feature vector
  raises `FeatureHashMismatchError`.
- The ledger links a prediction to an artifact through the existing
  `model_version` column with the convention
  `<version>@<artifact_id[:12]>` (for example `logit-v1@0123456789ab`).
  `resolve_prediction(prediction)` loads that artifact and requires the
  prediction's `features_hash` to match, so a foreign feature snapshot is
  refused. This is a convention carried in an existing column, not a schema
  field.
- `janus model list [--json]` lists artifacts; `janus model show <ref> [--json]`
  prints one. A missing or corrupt artifact exits 1 with
  `artifact not found: ...` or `artifact corrupt: ...` on stderr.

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

## Quantiles and interval coverage

`EmpiricalQuantileModel` turns point-in-time returns into 10/50/90 quantiles.
It is distribution-free, records the sample size, and scales horizon width by
`sqrt(horizon)`. `coverage` measures how often outcomes land inside the central
interval; intervals widen when the supplied return history is more volatile.

## Scenario trees

`generate_scenario_tree` builds deterministic `up` / `base` / `down` branches
with assumptions, catalysts, risks, falsifiers, and evidence. The numeric
probabilities sum to one and are validated by `ScenarioTree`; an LLM may enrich
the narrative later but never owns the numbers. The model is validated by Pydantic and
can export its own JSON Schema without changing the domain contract version.

## Walk-forward evaluation

`WalkForwardSplitter` creates rolling train/test windows with explicit purge and
embargo gaps. `WalkForwardBacktester` re-fits the model per fold, reports Brier,
log loss, accuracy, gross and net returns, and turnover. Costs are reported in
basis points; no performance number is meaningful without them. Non-monotonic
timestamps raise `LeakDetected`, and the same inputs produce the same report.

## Counterfactual replay

`CounterfactualReplay` answers "what if we only knew X?" from the prediction's
`as_of` snapshot. It can remove evidence ids, add observations that were valid
and published at that time, override feature values, or swap the persona. The
report keeps the recorded probability separate from the replayed baseline and
explains the delta. Swapped evidence published after `as_of` raises
`CounterfactualLeak`; the original evidence list never contains future rows.

```bash
janus counterfactual <prediction-id> --remove <observation-id> --persona <id>
```

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
