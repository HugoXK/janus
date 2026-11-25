# v0.1.0 release plan

**Status:** v0.1.0 is released. v0.1.1 is in progress: process hardening is
merged; the data spine (GDELT/RSS, scheduler, data quality) is in review.

## Goal

A local-first, point-in-time market agent with:

- free data: prices, filings, macro, news;
- memory: bitemporal store, entity graph, provenance, snapshots;
- analysis: indicators, breadth, regime, sector, fundamentals, feature store;
- forecast: probabilistic models, calibration, settlement, walk-forward;
- review: debrief, attribution, calibration, persona comparison;
- interface: CLI, MCP server, DSH panels and commands;
- evaluation: BeliefBench, metrics, baselines;
- security and compliance: secret scanning, source terms, disclaimers.

## Process

1. No direct pushes to `main`. Every change lands through a pull request.
2. A pull request needs a review and green checks before merge.
3. Required checks: `tests-ok`, `review-gate`, and `merge-gate`.

## PR plan

| PR | Scope | Issues |
| --- | --- | --- |
| #1 | Data foundation, provenance, review/CI | JAN-008, JAN-010, JAN-016, JAN-019, JAN-049, JAN-050 |
| #2 | Analysis, feature store, dashboards | JAN-023, JAN-024, JAN-025, JAN-027 |
| #3 | Forecast, calibration, review, persona | JAN-028, JAN-033, JAN-034, JAN-035, JAN-037 |
| #4 | MCP, DSH, BeliefBench, release | JAN-040, JAN-041, JAN-042, JAN-045, JAN-046, JAN-047, JAN-048 |

## Definition of done for v0.1.0

- `git clone && make demo` runs offline; no paid API required.
- Free data adapters: Tiingo, yfinance, SEC EDGAR, FRED / ALFRED.
- Bitemporal store with published/observed modes, snapshots, and provenance.
- Entity graph resolves ticker, CIK, and common names.
- Market, sector, and stock dashboard contracts are versioned.
- A baseline probabilistic forecast is recorded before its outcome and scored
  after it.
- Calibration dashboard reports Brier, ECE, reliability, and coverage.
- A debrief records attribution and lessons.
- Persona switching changes the evidence ranking and is auditable.
- MCP tools and CLI commands expose the core.
- BeliefBench runs as-of scenarios without lookahead.
- CI is green: lint, tests on 3.11/3.12, coverage, schema, demo, wheel, DSH
  plugin, secret scan, review gate.
- No secrets, no broker integration, no return promises, no investment advice.

## Versioning

- `v0.1.0` is the first usable local research agent.
- `v0.1.x` fixes correctness, data quality, and review findings.
- `v0.2.0` adds the DSH UI panels, richer scenarios, and persona evolution.
