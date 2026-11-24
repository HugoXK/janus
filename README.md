# Janus

<p align="center">
  <b>Look back to reason forward.</b><br>
  A market agent with memory and foresight.
</p>

> **Status:** `v0.1.0` scaffold. The repository contains the core data model, a
> point-in-time store, technical indicators, a prediction ledger, calibration
> primitives, persona profiles, and a DSH plugin skeleton. It is not investment
> advice and it does not execute trades.

Janus is a market agent with two faces. **Memory** records what you believed,
what you knew, and how it turned out. **Foresight** turns that record into
calibrated probabilities about what comes next.

Most market tools either drown you in data or sell you a prediction. Janus keeps
the evidence, remembers the reasoning, and tells you when you were wrong. It is
local-first, point-in-time, and built to be audited.

## Why the name

Janus is the Roman god of gates, transitions, beginnings, and endings. He is
shown looking both ways because every threshold is an ending and a beginning.
January is named after him: the month where the old year closes and the new one
opens.

Markets are full of thresholds. Janus is the instrument for them.

The two faces are not duplicity. They are two disciplines held at once:
**memory** and **foresight**. One face asks, "What did I believe, and why?" The
other asks, "What is the probability now?"

## What Janus is

- **Memory (the past):** every observation, thesis, prediction, and outcome is
  recorded with its source, timestamp, and provenance.
- **Foresight (the future):** technical, fundamental, macro, sentiment, breadth,
  and flow features are combined into probabilistic forecasts, scenarios, and
  regime probabilities.
- **A closed loop:** observe → analyze → predict → decide (paper) → review →
  calibrate → improve.
- **Personal:** watchlists, holdings, risk budget, and an explicit investment
  "taste" profile.
- **Actually open:** local-first, free-data default, model-agnostic, and
  reproducible. The core loop does not require a paid API.

## What Janus is not

- Not a stock picker, a trading bot, or a broker integration.
- Not a promise of returns.
- Not "another chat with your portfolio".
- Not a full Bloomberg terminal.
- Not a hindsight machine: every forecast is recorded before its outcome.

## The loop

```
Observe → Analyze → Predict → Decide (paper) → Review → Calibrate → Improve
   ↑                                                                    │
   └──────────────────── memory / provenance ──────────────────────────┘
```

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

Design rules:

1. **LLMs reason; software computes.** Indicators, backtests, and calibration
   are deterministic Python.
2. **Free by default.** The core loop runs on free data and local/open models.
3. **Point-in-time or it didn't happen.** Every query supports `as_of`; every
   conclusion carries provenance.

## Quickstart

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --extra dev
uv run janus demo
```

Or with make:

```bash
make install
make demo
make test
```

The demo runs fully offline with sample data. It shows an as-of query, a small
technical signal, a recorded prediction, and a calibration result.

## Data sources (free default stack)

| Need | Default | Fallback |
| --- | --- | --- |
| Prices | Tiingo EOD | yfinance, Stooq |
| Fundamentals / filings | SEC EDGAR | FMP, Alpha Vantage |
| Macro | FRED / ALFRED | World Bank, IMF |
| News / events | GDELT | Marketaux, NewsAPI, RSS |
| China | AkShare | BaoStock, Tushare |

Paid providers are optional enhancements, never a requirement for the core loop.
Respect each provider's terms of service; do not redistribute data.

## Repository layout

```
core/janus/        Python core: data, memory, analysis, forecast, review, persona
dsh-plugin/        DSH plugin (TypeScript): panels, commands, cron
docs/              Architecture, data model, ADRs
tests/             Point-in-time, indicator, and ledger tests
examples/          Offline demo data and scripts
```

## Roadmap

- [x] Repository scaffold
- [ ] Point-in-time store and as-of queries
- [ ] Free data adapters (Tiingo, yfinance, SEC, FRED, GDELT)
- [ ] Technical indicator engine
- [ ] Market / sector / stock dashboards
- [ ] Probabilistic forecast ledger and calibration
- [ ] Thesis tracker and review/debrief
- [ ] 10-question taste profile and persona switching
- [ ] DSH plugin (panels, commands, cron)
- [ ] BeliefBench: lookahead-free evaluation

## Disclaimer

Janus is for research and education. It is not investment advice. It does not
execute trades. Past performance and backtests do not guarantee future results.
Consult a licensed financial advisor before making investment decisions.

## License

Apache-2.0. See [LICENSE](LICENSE).
