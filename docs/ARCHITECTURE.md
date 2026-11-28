# Architecture

## Goal

Janus is a closed loop for market beliefs:

```
Observe → Analyze → Predict → Decide (paper) → Review → Calibrate → Improve
   ↑                                                                    │
   └──────────────────── memory / provenance ──────────────────────────┘
```

The stock market is the testbed. The durable technical asset is the
point-in-time memory, the prediction ledger, and the calibration loop.

## Layers

| Layer | Language | Responsibility |
| --- | --- | --- |
| Shell | TypeScript (DSH plugin) | Panels, commands, cron, approvals, chat |
| Contract | MCP | Tool and resource boundary between shell and core |
| Core | Python | Data, memory, analysis, forecast, review, persona |
| Storage | SQLite (V1) → Postgres (later) | Point-in-time observations, theses, predictions, outcomes |
| Data | HTTP adapters | Tiingo, yfinance, SEC EDGAR, FRED/ALFRED, GDELT, RSS |

## Why DSH as the shell

- Plugin model: skill / hook / cron / memory are first-class.
- Local-first and browser-based.
- Reuses FlyBot and bot-social for scheduling, approvals, and sharing.
- The Python core stays independent, so the shell can be replaced by any MCP
  client (Claude, ChatGPT, OpenCode, Cursor).

## Why not a generic "superagent"

A generic agent loop is not the moat. The moat is the memory schema, the
point-in-time queries, the prediction ledger, and the calibration loop. A thin
agent over thick deterministic tools is easier to audit and harder to fake.

## Data flow

1. Adapters write `Observation` rows with `published_at`, `observed_at`, and
   `valid_from` / `valid_to`.
2. The analysis layer reads only as-of views and computes indicators, breadth,
   regime, and sector features.
3. The forecast layer writes an immutable `Prediction` before the outcome exists.
4. The review layer settles the prediction, attributes the result, and records a
   `Review`.
5. The persona layer re-weights features and horizons based on the user's taste
   profile and, later, on walk-forward outcomes.

## Module map

```
core/janus/
  data/          adapters and the DataSource contract
  memory/        models, SQLite store, as-of helpers
  analysis/      indicators, breadth, regime, sector
  forecast/      ledger, calibration, baseline engine
  thesis/        thesis tracker
  review/        debrief and attribution
  persona/       profile vector and master priors
  eval/          BeliefBench and walk-forward skeleton
  share/         approval-first signed sharing
  mcp/           optional MCP server
  logging.py     JSON logs, correlation scopes, value-level redaction
  cli.py         local CLI
  demo.py        offline end-to-end demo
```

## Logging and correlation

`core/janus/logging.py` provides one structured event path and is wired into the
running program: the CLI `@app.callback()` exposes `--log-format text|json` and
`--log-level`, both routed through `configure_logging()`, and the ingestion
scheduler emits `ingestion.start`, `ingestion.dead_letter`, and
`ingestion.complete` events with the run id. `log_event()` merges the active
`correlation_scope()` fields (for example `run_id`, `source`, `entity_id`, and
`as_of`) into one JSON object per line.

Redaction is **value-level**, not key-name-level: `redact()` scans every string
at any depth, so a provider or HTTP error carrying `?api_key=...`,
`Authorization: Bearer ...`, a PEM private-key block, a `sk-…`/`sk_live_…`/
`ghp_…`/`AKIA…` token shape, or `https://user:pass@host` userinfo is masked
whether or not its mapping key looks sensitive. `JsonFormatter` scrubs
`message`, `event`, and `exception`; `TextFormatter` scrubs the rendered line.
Keys that look sensitive are masked wholesale, and structured event fields can
never overwrite the `timestamp`/`level`/`logger`/`message` envelope.

## Non-goals for V1

- Real trading or broker integration.
- Options, futures, or crypto.
- A full fundamental database.
- A generic chat interface.
- Point price predictions or return promises.
