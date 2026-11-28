<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/janus-wordmark-dark.svg">
    <img src="docs/images/janus-wordmark.svg" alt="Janus" width="420">
  </picture>
</p>

<p align="center">
  <b>Look back to reason forward.</b><br>
  A market agent with memory and foresight: it remembers what you believed, and
  turns that memory into calibrated probabilities about what comes next.
</p>

<p align="center">
  <a href="https://github.com/HugoXK/janus/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/HugoXK/janus/actions/workflows/ci.yml/badge.svg?branch=main"></a>
  <img alt="Python" src="https://img.shields.io/badge/python-%E2%89%A53.11-3776AB?logo=python&logoColor=white">
  <img alt="DSH" src="https://img.shields.io/badge/DSH-plugin-3B5BFD">
  <img alt="MCP" src="https://img.shields.io/badge/MCP-server-6366f1">
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-Apache_2.0-green"></a>
  <img alt="Status" src="https://img.shields.io/badge/status-v0.1%20scaffold-orange">
</p>

<p align="center">English | <a href="README.zh.md">中文</a></p>

---

> **Status:** `v0.1.0` scaffold. The point-in-time store, indicator engine,
> prediction ledger, calibration primitives, persona profile, and DSH plugin
> skeleton are in place. Live data adapters, the market / sector / stock
> dashboards, the full forecast engine, and the review workflow are next. This is
> research tooling: not investment advice, and it does not execute trades.

Janus is a market agent with two faces. **Memory** records what you believed,
what you knew, and how it turned out. **Foresight** turns that record into
calibrated probabilities about what comes next.

Most market tools either drown you in data or sell you a prediction. Janus keeps
the evidence, remembers the reasoning, and tells you when you were wrong. It is
local-first, point-in-time, and built to be audited.

## Table of contents

- [Why Janus](#why-janus)
- [What it is](#what-it-is)
- [What it is not](#what-it-is-not)
- [What the scaffold proves today](#what-the-scaffold-proves-today)
- [Feature status](#feature-status)
- [How it works](#how-it-works)
- [Architecture](#architecture)
- [Quick start](#quick-start)
- [Demo](#demo)
- [Data sources](#data-sources)
- [Repository layout](#repository-layout)
- [Roadmap](#roadmap)
- [Evaluation](#evaluation)
- [Security and privacy](#security-and-privacy)
- [FAQ](#faq)
- [Contributing](#contributing)
- [License](#license)
- [Built with](#built-with)

## Why Janus

The market is noisy, adversarial, and non-stationary. That makes it a good place
to test a memory-and-foresight system:

- every claim has a timestamp;
- every forecast has an outcome;
- every outcome can be scored;
- every regime change punishes a stale memory.

Most open finance agents optimize for a trading decision. Janus optimizes for the
loop that makes decisions better over time:

```
Observe → Analyze → Predict → Decide (paper) → Review → Calibrate → Improve
   ↑                                                                    │
   └──────────────────── memory / provenance ──────────────────────────┘
```

The name comes from the Roman god of gates, transitions, beginnings, and
endings. **January** is named after him. Markets are full of thresholds. Janus
stands at the threshold with two faces: one remembers, one reasons forward.

The two faces are not duplicity. They are the two disciplines of the product:
**Memory** and **Foresight**. The name is an instrument, not an oracle.

See [docs/adr/0001-name.md](docs/adr/0001-name.md) for the full naming decision
and [docs/BRAND.md](docs/BRAND.md) for the copy and visual system.

## What it is

- A **personal, point-in-time market memory**: observations, theses, forecasts,
  and outcomes with provenance.
- A **probabilistic forecast ledger** with calibration, not a price oracle.
- An **analysis engine** for market, sector, and stock features.
- A **DSH plugin** and an **MCP server** over a Python core.
- **Local-first, free-data by default, model-agnostic.**

## What it is not

- Not a stock picker or a trading bot.
- Not a broker integration; it does not execute trades.
- Not a promise of returns.
- Not a full Bloomberg terminal.
- Not a hindsight machine: every forecast is written before its outcome.
- Not investment advice.

## What the scaffold proves today

No performance claims yet. The scaffold proves the invariants:

| Invariant | Where |
| --- | --- |
| Domain contracts and JSON Schema are frozen | `schemas/janus.schema.json`, `tests/test_contracts.py` |
| Schema migrations are deterministic and idempotent | `tests/test_migrations.py`, `janus migrate` |
| Config precedence and doctor are tested | `tests/test_config.py`, `janus config doctor` |
| Future observations never enter an as-of view | `tests/test_asof.py` |
| Published and observed query modes, snapshots, pagination | `tests/test_asof.py` |
| As-of properties hold under generated inputs | `tests/test_asof_hypothesis.py` |
| Tiingo maps adjusted prices and re-ingestion is idempotent | `tests/test_tiingo.py` |
| Entity graph resolves ticker, CIK, and names | `tests/test_entities.py` |
| Security master and universe membership are point-in-time | `tests/test_security_master.py` |
| Corporate actions drive an explicit, replayable price adjustment | `tests/test_corporate_actions.py` |
| Citations resolve to exact source spans, not summaries | `tests/test_source_spans.py` |
| Provenance trace and as-of search | `tests/test_provenance.py` |
| yfinance maps adjusted close | `tests/test_yfinance.py` |
| FRED latest and ALFRED vintage | `tests/test_fred.py` |
| SEC restatement keeps the as-filed fact | `tests/test_sec_edgar.py` |
| Public copy has no return promises | `tests/test_copy.py` |
| Breadth, regime, and sector rotation are deterministic | `tests/test_breadth.py`, `tests/test_regime.py`, `tests/test_sector.py` |
| Features are point-in-time and hash-addressed | `tests/test_features.py` |
| Dashboard contracts validate | `tests/test_dashboards.py` |
| Baseline logistic model and model card | `tests/test_baseline_model.py` |
| Calibration service (Platt / isotonic) | `tests/test_calibration_service.py` |
| Settlement resolves direction and prevents double settlement | `tests/test_settlement.py` |
| Debrief attribution sums to one | `tests/test_debrief.py` |
| Persona weighting changes evidence ranking | `tests/test_persona_weighting.py` |
| MCP service round-trip | `tests/test_mcp_service.py` |
| BeliefBench runner and baselines | `tests/test_beliefbench.py` |
| GDELT and RSS map to observations | `tests/test_gdelt.py`, `tests/test_rss.py` |
| Retries, dead letters, replay, and contained store failures | `tests/test_scheduler.py` |
| Forecast/review CLI workflows are scriptable and tested | `tests/test_cli_forecast_review.py` |
| Counterfactual replay and persona tournaments are deterministic | `tests/test_counterfactual.py`, `tests/test_persona_tournament.py` |
| Blobs are content-addressed and GC keeps referenced payloads | `tests/test_blob.py` |
| Quantile/scenario tools are exposed through the MCP service | `tests/test_forecast_interface.py` |
| Quantiles, scenarios, and walk-forward costs/leaks are tested | `tests/test_quantiles.py`, `tests/test_scenarios.py`, `tests/test_backtest.py` |
| Brief/snapshot CLI commands are scriptable | `tests/test_cli_brief_snapshot.py` |
| Local API exposes request metrics and X-Request-ID | `tests/test_server.py` |
| Local JSON API publishes an OpenAPI contract | `tests/test_server.py` |
| DSH dock/cron reads the local JSON panel API | `tests/test_server.py` |
| Shared SQLite access is serialized across worker threads | `tests/test_store_threading.py` |
| Conflicting facts keep both sides and resolve by an audited policy | `tests/test_conflicts.py` |
| Fundamentals are as-filed, provenance-linked, and event flags cite ids | `tests/test_fundamentals.py` |
| Snapshot archives are tamper-evident and replay identical features | `tests/test_snapshot_archive.py` |
| Retention deletes only expired rows; redaction is deep and non-mutating | `tests/test_retention.py` |
| Quality checks catch duplicate, future, and stale data | `tests/test_quality.py` |
| Predictions are immutable and settle once | `tests/test_ledger.py` |
| RSI stays bounded; MACD / Bollinger / OBV behave | `tests/test_indicators.py` |
| The offline loop runs without a paid API and matches a golden file | `tests/test_demo_golden.py` |

The demo shows 20 visible observations, excludes a future row, computes RSI,
records a prediction, settles it, computes Brier / ECE on a toy sample, and
matches a taste profile. The numbers are a smoke test, not a benchmark.

## Feature status

| Area | Now | Next |
| --- | --- | --- |
| **Memory** | Bitemporal store, published/observed modes, snapshots, entity graph, provenance | Dedup, retention, snapshot export |
| **Foresight** | Prediction ledger, baseline logistic model, calibration service, settlement | Quantiles, scenarios, model registry |
| **Analysis** | RSI/MACD/ATR/Bollinger/OBV, breadth, regime, sector RRG, feature store, dashboard contracts | DSH panels and the full UI |
| **Review** | Debrief and attribution baseline | Counterfactual replay |
| **Taste** | 10-question profile, master priors, persona-conditioned evidence ranking | Persona evolution |
| **Interface** | CLI, MCP server, DSH plugin panel/command descriptors | DSH UI wiring, approvals, cron |
| **Evaluation** | BeliefBench schema/runner, metrics, baselines | More benchmarks and live tasks |
| **Data** | Tiingo, yfinance, SEC EDGAR, FRED / ALFRED, GDELT, RSS, scheduler, data quality, cache, blob store | Options/sentiment, China adapters |

## How it works

### Three timestamps

Every observation carries three times:

- `published_at` — when the world could have known it;
- `observed_at` — when Janus actually ingested it;
- `valid_from` / `valid_to` — the fact's own validity window.

An as-of query uses `published_at` and the validity window. Future rows may sit
in the same database; they are simply invisible to a historical view. This is
the difference between a backtest and a fantasy.

### The prediction ledger

A forecast is written before the outcome, with its probability, horizon, model
version, and a hash of the features used. There is no edit path for the forecast
itself. The only allowed mutation is attaching an outcome later. A prediction
that cannot be wrong cannot be calibrated.

### The calibration loop

After the outcome, Janus scores the forecast, attributes the result, and writes a
review. Over time the ledger answers questions a single backtest cannot:

- Is the model overconfident in high-volatility regimes?
- Does RSI help in ranges but hurt in trends?
- Which persona is well calibrated, and on what horizon?
- What did we believe before the evidence changed?

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      DSH (TypeScript)                    │
│  UI: Market / Sector / Stock / Thesis / Calibration      │
│  Agent loop · cron · approvals · skill                   │
└───────────────────────────┬─────────────────────────────┘
                            │ MCP
┌───────────────────────────▼─────────────────────────────┐
│                    Janus Core (Python)                   │
│  data → memory → analysis → forecast → review → persona  │
│  bitemporal store · entity graph · feature store         │
│  calibration · BeliefBench · CLI                         │
└───────────────────────────┬─────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
   Free data           Local models        Optional paid
   Tiingo/yfinance     DeepSeek/Qwen       Polygon/FMP
   SEC/FRED/GDELT      Ollama/vLLM         (enhancements)
```

**Why DSH as the shell.** The plugin model gives us panels, commands, cron, and
approvals without rebuilding a UI. It also connects to FlyBot and bot-social for
scheduling and sharing.

**Why Python as the core.** Data ingestion, indicators, filings, backtests, and
calibration live in the Python ecosystem. The core is usable without DSH: CLI
and MCP first.

**Why MCP as the contract.** The core should be reachable from Claude, ChatGPT,
OpenCode, Cursor, or a local script. DSH is the first shell, not the only one.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and
[docs/adr/0002-architecture.md](docs/adr/0002-architecture.md).

## Quick start

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --extra dev
uv run janus demo
uv run pytest
```

Or with make:

```bash
make install
make demo
make test
```

A plain `pip` fallback:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
janus demo
```

The demo is fully offline. It uses no API key and no network.

## Demo

```text
Janus demo
============================================================
as_of:                 2026-01-15T00:00:00+00:00
observations visible:  20 (future row excluded)
current RSI(14):       85.5
thesis:                ACME remains constructive while RSI stays above 50 and price...
prediction:            P(up over 1M) = 0.65
prediction settled:    True
brier score:           0.1175
expected calib. error: 0.3333
taste match:           Lynch (0.96)
============================================================
This demo is research tooling, not investment advice.
```

The numbers come from a toy sample. They demonstrate the mechanics, not skill.

## Command-line quickstart

```bash
janus brief AAPL --json
janus snapshot AAPL --as-of 2026-01-02T00:00:00+00:00 --out snap.json
```

## Data sources

Free by default; paid providers are optional enhancements. Respect every
provider's terms of service and do not redistribute licensed data.

| Need | Default | Fallback | Notes |
| --- | --- | --- | --- |
| Prices | Tiingo EOD | yfinance, Stooq | yfinance is unofficial and can break |
| Fundamentals / filings | SEC EDGAR | FMP, Alpha Vantage | SEC is authoritative; set a User-Agent |
| Macro | FRED / ALFRED | World Bank, IMF | Use ALFRED vintages for point-in-time |
| News / events | GDELT | Marketaux, NewsAPI, RSS | GDELT is noisy; RSS is stable |
| China | AkShare | BaoStock, Tushare | Scraping adapters need fallbacks |

Known traps: delayed or unofficial prices, restated fundamentals, survivorship
bias, corporate actions, publisher vs ingest time, duplicate news, ticker
changes. The store keeps enough metadata to handle them explicitly.

## Repository layout

```
core/janus/
  data/          adapter contracts and the free-source adapters
  memory/        models, SQLite store, as-of helpers
  analysis/      indicators, breadth, regime, sector
  forecast/      prediction ledger, calibration, baseline engine
  thesis/        thesis tracker
  review/        debrief and attribution
  persona/       profile vector and master priors
  eval/          BeliefBench and walk-forward skeleton
  mcp/           optional MCP server
  cli.py         local CLI
  demo.py        offline end-to-end demo

dsh-plugin/      DSH plugin (TypeScript): panels, commands, cron
docs/            architecture, data model, forecasting, brand, ADRs
tests/           point-in-time, indicator, and ledger tests
examples/        offline demo entry point
```

## Roadmap

The full 50-issue plan lives in [docs/BACKLOG.md](docs/BACKLOG.md). The v0.1.0 release plan is in [docs/RELEASE_0.1.0.md](docs/RELEASE_0.1.0.md).

- [x] Repository scaffold
- [x] Domain contracts and JSON Schema
- [x] Schema migrations
- [x] Config loader and `janus config doctor`
- [x] Golden demo and property-based as-of tests
- [x] Point-in-time store and as-of queries
- [x] Published/observed query modes, snapshots, and pagination
- [x] Tiingo EOD adapter
- [x] yfinance fallback adapter
- [x] SEC EDGAR submissions and XBRL adapter
- [x] FRED / ALFRED vintage adapter
- [x] Entity graph and alias resolution
- [x] Provenance traversal API
- [x] Review gate, merge gate, and PR workflow
- [x] Secret scan and release workflows
- [x] GDELT event ingestion
- [x] RSS / IR ingestion
- [x] Ingestion scheduler and dead-letter queue
- [x] Data quality checks
- [x] Technical indicator engine
- [x] Breadth, regime, and sector rotation features
- [x] Point-in-time feature store
- [x] Market / sector / stock dashboard contracts
- [x] Prediction ledger and calibration primitives
- [x] Baseline direction model
- [x] Calibration service (Platt / isotonic)
- [x] Forecast settlement and outcome resolver
- [x] Debrief and attribution baseline
- [x] Persona-conditioned evidence weighting
- [x] Persona profile and master priors
- [x] Offline demo and tests
- [ ] DSH UI wiring for market / sector / stock dashboards
- [ ] Full forecast engine and scenario trees
- [x] Thesis tracker and debrief baseline
- [ ] Counterfactual replay
- [x] MCP server v1
- [x] DSH plugin panel and command descriptors
- [ ] DSH UI wiring and cron
- [x] BeliefBench: lookahead-free evaluation
- [x] Evaluation metrics and baselines
- [ ] V1.1: options / sentiment features, AgentDescent persona evolution
- [ ] V1.2: multi-market, portfolio construction, collaboration

## Evaluation

Janus does not claim alpha. It claims that its forecasts can be checked.

**BeliefBench** (planned) is a lookahead-free harness:

- historical as-of scenarios with a resolution date;
- evidence grounding: every claim must cite a source span;
- point-in-time correctness: no future data, no restated facts;
- calibration: Brier, log loss, reliability, ECE;
- robustness: regime splits, horizon splits, persona splits.

Baselines will include random, always-up, RSI-only, and buy-and-hold. No
performance number will be published without a walk-forward run, transaction
costs, and a stated sample.

## Security and privacy

- Local-first by default; SQLite at `~/.janus/janus.db`.
- No broker credentials, no order execution, no real money.
- No secrets in the repository; `.env`, keys, and local data are ignored.
- Data stays on your machine unless you explicitly export it.
- Janus is not investment advice. In China, securities investment advisory
  requires a license; Janus is positioned as personal research tooling, not a
  recommendation service.

## FAQ

**Is this financial advice?**
No. It is research tooling. It does not recommend buys or sells.

**Does it predict prices?**
No. It produces probabilities, scenarios, and regime estimates, and it scores
them afterward.

**Do I need paid APIs?**
No. The core loop is designed to run on free data and local models. Paid
providers are optional.

**Does it trade?**
No. There is no broker integration in V1.

**Why the name Janus?**
Janus is the Roman god of gates and transitions; January is named after him. The
two faces are memory and foresight, not duplicity. See
[docs/adr/0001-name.md](docs/adr/0001-name.md).

**Why DSH?**
The plugin model gives us a UI, cron, and approvals without rebuilding a
platform. The Python core stays independent, so the shell can change.

**Can I use it with Claude, ChatGPT, or OpenCode?**
Yes, through the MCP server. DSH is the first shell, not the only one.

**How is this different from other open finance agents?**
Most optimize for a trading decision. Janus optimizes for a memory-and-calibration
loop: point-in-time evidence, an immutable forecast ledger, and a review that
changes the next forecast.

**What is the hardest technical part?**
Point-in-time correctness and calibration. The LLM is not the hard part.

**Is it production-ready?**
No. It is a `v0.1.0` scaffold. Use it to explore, not to manage money.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The short version:

- point-in-time or it didn't happen;
- LLMs reason, software computes;
- no advice, no execution, no return promises;
- free by default;
- small surfaces, tested invariants.

## License

Apache-2.0. See [LICENSE](LICENSE).

## Built with

- [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) for the
  plugin shell and agent loop.
- [MCP](https://modelcontextprotocol.io/) for the tool contract.
- Python, pandas, NumPy, SQLite.
- Ideas and patterns from the author's other work: FlyBot, bot-social,
  AgentDescent, and Fledge. Janus is an independent project and does not claim
  affiliation with them.
