# Janus backlog — 50 issues

This is the implementation plan for the `v0.1` scaffold to a usable V1. Each
entry is written to become a GitHub issue without rewriting: it has a stable id,
labels, a milestone, dependencies, context, tasks, and testable acceptance
criteria.

## How to read this

**Current status (2026-11-24):** JAN-001, JAN-002, JAN-003, JAN-005, JAN-007, JAN-018, JAN-021, JAN-026, JAN-029, JAN-030, JAN-032, JAN-036, JAN-038, JAN-039,
JAN-008, JAN-009, JAN-010, JAN-015, JAN-016, JAN-019, JAN-023, JAN-024, JAN-025,
JAN-027, JAN-028, JAN-031 (tracker #39 / JAN-074), JAN-033, JAN-034, JAN-035,
JAN-037, JAN-040, JAN-041,
JAN-045, JAN-046, JAN-047, JAN-048, JAN-049, JAN-050, JAN-058, JAN-059,
JAN-060, and JAN-061 are implemented. JAN-022 is implemented. JAN-042 has the
command/panel descriptors; DSH UI wiring and cron are deferred to v0.2. See
JAN-060, and JAN-061 are implemented. JAN-041 and JAN-042 are implemented: DSH
dock/panels, commands, HTTP panel API, and daily brief cron. See
`schemas/janus.schema.json`,
`tests/test_contracts.py`,
`tests/test_migrations.py`, `tests/test_config.py`,
`tests/test_asof_hypothesis.py`, `tests/test_tiingo.py`,
`tests/test_sec_edgar.py`, `tests/test_entities.py`, `tests/test_provenance.py`,
`tests/test_yfinance.py`, `tests/test_fred.py`, `tests/test_breadth.py`,
`tests/test_regime.py`, `tests/test_sector.py`, `tests/test_features.py`,
`tests/test_dashboards.py`, `tests/test_baseline_model.py`,
`tests/test_calibration_service.py`, `tests/test_settlement.py`,
`tests/test_debrief.py`, `tests/test_persona_weighting.py`,
`tests/test_mcp_service.py`, `tests/test_beliefbench.py`,
`tests/test_gdelt.py`, `tests/test_rss.py`, `tests/test_scheduler.py`,
`tests/test_quality.py`, `tests/test_counterfactual.py`,
`tests/test_persona_tournament.py`, `tests/test_blob.py`,
`tests/test_quantiles.py`, `tests/test_scenarios.py`, `tests/test_backtest.py`,
`tests/test_server.py`, `tests/test_conflicts.py`, `tests/test_copy.py`,
`tests/test_retention.py`, `tests/test_mcp_scoped_auth.py`,
`tests/test_fundamentals.py`, `tests/test_persona_evolution.py`, and `tests/test_snapshot_archive.py`.

- **Milestones** are delivery windows, not promises: M0 foundation, M1 data and
  memory, M2 analysis, M3 forecast and review, M4 interface, M5 evaluation and
  release.
- **Priority** is P0 (blocks V1), P1 (needed for a credible V1), P2 (V1.1+).
- **Depends** lists the issue ids that must land first.
- **Acceptance** is written as evidence, not adjectives.

## Labels

`area:core` `area:data` `area:memory` `area:analysis` `area:forecast`
`area:review` `area:persona` `area:interface` `area:eval` `area:security`
`area:dx` `area:docs`

`type:feature` `type:task` `type:test` `type:design` `type:research`
`type:docs`

`priority:P0` `priority:P1` `priority:P2`
`size:S` `size:M` `size:L`
`good-first-issue`

## Summary

| Id | Title | Milestone | Priority |
| --- | --- | --- | --- |
| JAN-001 | Freeze the v0.1 domain contracts | M0 | P0 |
| JAN-002 | Add schema migrations and a version table | M0 | P0 |
| JAN-003 | Configuration loader and `janus config doctor` | M0 | P0 |
| JAN-004 | Structured logging and correlation ids | M0 | P1 |
| JAN-005 | Golden demo and property-based as-of tests | M0 | P0 |
| JAN-006 | Release automation and package metadata | M0 | P1 |
| JAN-007 | Tiingo EOD adapter | M1 | P0 |
| JAN-008 | yfinance fallback adapter | M1 | P0 |
| JAN-009 | SEC EDGAR submissions and XBRL adapter | M1 | P0 |
| JAN-010 | FRED / ALFRED vintage adapter | M1 | P0 |
| JAN-011 | GDELT event ingestion | M1 | P1 |
| JAN-012 | RSS / IR ingestion and canonicalization | M1 | P1 |
| JAN-013 | Ingestion scheduler, retries, and dead-letter queue | M1 | P0 |
| JAN-014 | Data quality checks and source timestamps | M1 | P0 |
| JAN-015 | Harden the bitemporal query API | M1 | P0 |
| JAN-016 | Entity graph and alias resolution | M1 | P0 |
| JAN-017 | Content-addressed dedup and blob store | M1 | P1 |
| JAN-018 | Source credibility and conflict resolution | M1 | P1 |
| JAN-019 | Provenance traversal API | M1 | P0 |
| JAN-020 | Retention, redaction, and encryption at rest | M1 | P1 |
| JAN-021 | As-of snapshot export / import and corpus lineage | M1 | P1 |
| JAN-022 | Indicator engine v1 | M2 | P0 |
| JAN-023 | Breadth indicators | M2 | P0 |
| JAN-024 | Volatility and regime features | M2 | P0 |
| JAN-025 | Sector rotation and relative strength | M2 | P0 |
| JAN-026 | Fundamentals and event features | M2 | P1 |
| JAN-027 | Point-in-time feature store and dashboard contracts | M2 | P0 |
| JAN-028 | Baseline direction model with calibration | M3 | P0 |
| JAN-029 | Quantile and interval forecasts | M3 | P1 |
| JAN-030 | Scenario tree generator | M3 | P1 |
| JAN-031 | Model registry and feature-hash reproducibility | M3 | P0 |
| JAN-032 | Walk-forward backtester | M3 | P0 |
| JAN-033 | Calibration service | M3 | P0 |
| JAN-034 | Forecast settlement and outcome resolver | M3 | P0 |
| JAN-035 | Debrief and attribution engine | M3 | P1 |
| JAN-036 | Counterfactual replay | M3 | P1 |
| JAN-037 | Persona-conditioned retrieval and weighting | M3 | P1 |
| JAN-038 | Persona tournament | M3 | P1 |
| JAN-039 | AgentDescent persona evolution | M3 | P2 |
| JAN-040 | MCP server v1 | M4 | P0 |
| JAN-041 | DSH market / sector / stock panels | M4 | P0 |
| JAN-042 | DSH commands, daily brief, and cron | M4 | P0 |
| JAN-043 | Approvals and signed sharing | M4 | P1 |
| JAN-044 | CLI UX v1 | M4 | P1 |
| JAN-045 | BeliefBench scenario schema and loader | M5 | P0 |
| JAN-046 | BeliefBench runner and as-of guard | M5 | P0 |
| JAN-047 | Evaluation metrics suite | M5 | P0 |
| JAN-048 | Baselines and reproducible benchmark report | M5 | P0 |
| JAN-049 | Secrets, data licensing, and ToS policy | M5 | P0 |
| JAN-050 | Compliance copy, disclaimers, China guardrails | M5 | P0 |

---

## M0 — Foundation and developer experience

### JAN-001 — Freeze the v0.1 domain contracts

`area:core` `area:memory` `type:design` `priority:P0` `size:M` · **M0** · Depends: —

**Context.** `Observation`, `Thesis`, `Prediction`, `Outcome`, and `Review` are
the contract for every layer. Adding adapters before freezing them creates
migration debt.

**Tasks.**
- Document the invariants of each object and the immutability rules.
- Define enums, required fields, defaults, and timezone rules.
- Export JSON Schema and add contract tests.
- Add a `schema_version` field and a compatibility policy.
- Update `docs/DATA_MODEL.md`.

**Acceptance.**
- A generated `janus.schema.json` is checked in.
- Contract tests fail on an incompatible field change.
- The data model doc explains why three timestamps exist.

**Notes.** Keep V1 minimal. No broker, execution, or order fields.

### JAN-002 — Add schema migrations and a version table

`area:memory` `type:feature` `priority:P0` `size:M` · **M0** · Depends: JAN-001

**Context.** SQLite will evolve. Without deterministic migrations, a user's
local memory becomes unreadable after an upgrade.

**Tasks.**
- Add a `schema_migrations` table and a migration runner.
- Support a fresh database and an upgrade from the scaffold schema.
- Add `janus migrate` and a dry-run flag.
- Test idempotency and failure recovery.

**Acceptance.**
- Fresh and upgrade paths are tested in CI.
- Re-running migrations is a no-op.
- A failed migration leaves the database unchanged.

**Notes.** A small SQL folder is enough; Alembic is optional.

### JAN-003 — Configuration loader and `janus config doctor`

`area:dx` `type:feature` `priority:P0` `size:S` · **M0** · Depends: —

**Context.** Data sources need keys, paths, timezones, and model providers. A
bad config should fail before ingestion starts.

**Tasks.**
- Load `~/.janus/config.toml`, then environment variables, then CLI flags.
- Redact secrets in all output.
- Add `janus config doctor` for paths, keys, clock, and provider reachability.
- Document every key.

**Acceptance.**
- Precedence tests pass.
- `doctor` reports missing keys and unreachable providers.
- No secret is printed in logs or errors.

### JAN-004 — Structured logging and correlation ids

`area:dx` `type:feature` `priority:P1` `size:S` · **M0** · Depends: JAN-003

**Context.** Ingestion and MCP calls need traceable logs; a free-text log cannot
answer "which source failed for which entity at which as-of time?"

**Tasks.**
- Emit JSON logs with `run_id`, `entity_id`, `source`, and `as_of`.
- Add log levels and a `--log-format` flag.
- Redact secrets and personal data.
- Document the fields.

**Acceptance.**
- A demo run emits structured logs.
- A failing adapter produces a machine-readable error record.
- Tests cover redaction.

### JAN-005 — Golden demo and property-based as-of tests

`area:core` `area:memory` `type:test` `priority:P0` `size:M` · **M0** · Depends: JAN-001, JAN-002

**Context.** The demo is the first proof; as-of is the core invariant. Both
should be tested more aggressively than the rest of the scaffold.

**Tasks.**
- Add a golden file for `janus demo`.
- Add Hypothesis tests for as-of queries: future rows, valid windows, ties,
  timezone edges, duplicate ids.
- Add a fixture with a known future leak.
- Make failure messages explain the lookahead.

**Acceptance.**
- CI runs the golden test and the property tests.
- A deliberately future-dated row fails the guard.
- The error message names the offending observation and timestamp.

### JAN-006 — Release automation and package metadata

`area:dx` `type:task` `priority:P1` `size:M` · **M0** · Depends: JAN-001

**Context.** The project needs reproducible releases across PyPI, npm, and a
container image.

**Tasks.**
- Add a version bump and changelog workflow.
- Build sdist/wheel and a DSH plugin tarball.
- Add a container image target.
- Add `janus --version` and a release checklist.
- Keep `pyproject.toml`, `package.json`, and `__version__` in sync.

**Acceptance.**
- `make release` runs a dry-run end to end.
- CI uploads artifacts.
- Version strings match across packages.

---

## M1 — Data and memory

### JAN-007 — Tiingo EOD adapter

`area:data` `type:feature` `priority:P0` `size:M` · **M1** · Depends: JAN-001, JAN-003

**Context.** Tiingo is the primary free EOD source in the default stack.

**Tasks.**
- Authenticate, paginate, and respect rate limits.
- Cache responses with an explicit TTL.
- Handle adjusted vs unadjusted prices, splits, and dividends.
- Map rows to `Observation` with `published_at`, `observed_at`, and `raw_hash`.
- Add fixtures and an optional live smoke test.

**Acceptance.**
- Recorded fixtures produce stable observations.
- Re-ingestion is idempotent.
- The adapter is disabled by default without a key.

### JAN-008 — yfinance fallback adapter

`area:data` `type:feature` `priority:P0` `size:M` · **M1** · Depends: JAN-007

**Context.** When Tiingo is down or unconfigured, the demo still needs prices.

**Tasks.**
- Wrap yfinance with timeouts and a circuit breaker.
- Normalize adjusted close and corporate actions.
- Mark the source with lower confidence.
- Prevent double adjustment when both sources are present.

**Acceptance.**
- Fallback is selected only when the primary fails.
- Prices do not double-adjust.
- The adapter is clearly labelled unofficial in docs.

### JAN-009 — SEC EDGAR submissions and XBRL adapter

`area:data` `type:feature` `priority:P0` `size:L` · **M1** · Depends: JAN-001, JAN-003

**Context.** SEC EDGAR is the authoritative source for filings and as-filed
fundamentals. It is the backbone of provenance.

**Tasks.**
- Fetch submissions and company facts; add CIK/ticker mapping.
- Set a descriptive `User-Agent` and respect the rate limit.
- Parse 10-K/10-Q facts with accession numbers and filing dates.
- Distinguish as-filed from latest values.
- Store raw documents as blobs.

**Acceptance.**
- Fixtures for at least two companies parse correctly.
- Each fact links to an accession and a filing date.
- A restated value does not overwrite the as-filed value.

### JAN-010 — FRED / ALFRED vintage adapter

`area:data` `type:feature` `priority:P0` `size:M` · **M1** · Depends: JAN-003

**Context.** Macro data is revised. A backtest that uses today's revision is
lookahead.

**Tasks.**
- Fetch series metadata and observations.
- Support ALFRED real-time/vintage queries.
- Store the vintage date and the first-seen time.
- Document the revision policy.

**Acceptance.**
- An as-of query returns the value known at that date, not the latest revision.
- A vintage fixture is checked in.
- Docs explain when to use FRED vs ALFRED.

### JAN-011 — GDELT event ingestion

`area:data` `type:feature` `priority:P1` `size:M` · **M1** · Depends: JAN-001, JAN-016

**Context.** GDELT gives free global event data; it is noisy and needs entity
linking before it is useful.

**Tasks.**
- Ingest events and mentions for a configured watchlist.
- Extract actors, themes, locations, and tone.
- Deduplicate syndicated stories.
- Store language, source, and confidence.

**Acceptance.**
- A sample query returns linked entities and citations.
- Duplicate stories collapse to one observation.
- Docs state that GDELT is a signal, not a truth source.

### JAN-012 — RSS / IR ingestion and canonicalization

`area:data` `type:feature` `priority:P1` `size:M` · **M1** · Depends: JAN-001

**Context.** Company IR feeds and publisher RSS are stable, free, and
underrated. They also duplicate aggressively.

**Tasks.**
- Parse RSS/Atom with conditional GET.
- Canonicalize URLs and titles.
- Deduplicate exact and near-duplicate items.
- Respect robots and terms of service.

**Acceptance.**
- Fixtures for at least three feed shapes.
- Duplicate items produce one observation.
- No paywalled or disallowed scraping.

### JAN-013 — Ingestion scheduler, retries, and dead-letter queue

`area:data` `type:feature` `priority:P0` `size:M` · **M1** · Depends: JAN-007–JAN-012

**Context.** Daily ingestion must survive timeouts, rate limits, and partial
failures without blocking the whole run.

**Tasks.**
- Add a scheduler with per-source concurrency limits. *(landed in #73:
  `IngestionScheduler(max_concurrency=...)`, fetch-only pool, single-writer
  persistence in input order.)*
- Add exponential backoff and jitter.
- Persist failures in a dead-letter table with a replay command.
- Emit a run report with counts and latency.

**Acceptance.**
- A forced failure is recorded and replayable.
- One source failure does not abort the others.
- The run report is machine-readable.

### JAN-014 — Data quality checks and source timestamps

`area:data` `type:test` `priority:P0` `size:M` · **M1** · Depends: JAN-007–JAN-013

**Context.** Bad data silently corrupts memory. Quality checks must fail closed
for P0 sources.

**Tasks.**
- Check missing trading sessions, split/dividend consistency, stale feeds,
  duplicate rows, and extreme outliers.
- Check publisher time vs ingest time and timezone skew.
- Emit typed warnings with source and entity.
- Add a CI fixture for each class of bad data.

**Acceptance.**
- Each check has a failing fixture and a passing fixture.
- P0 source failures block the daily brief, not just log a warning.
- Docs list the checks and their severity.

### JAN-015 — Harden the bitemporal query API

`area:memory` `type:feature` `priority:P0` `size:M` · **M1** · Depends: JAN-001, JAN-002

**Context.** The scaffold supports `published_at` queries. Real research needs
both "what could have been known" and "what did we actually know".

**Tasks.**
- Add `published` and `observed` query modes.
- Support validity windows and snapshot ids.
- Add pagination and a stable sort.
- Add indexes and a benchmark on a large fixture.

**Acceptance.**
- Mode tests cover the two questions.
- A 1M-row query stays within the documented budget.
- The API is used by the provenance and feature layers.

### JAN-016 — Entity graph and alias resolution

`area:memory` `type:feature` `priority:P0` `size:L` · **M1** · Depends: JAN-015

**Context.** Tickers change, companies merge, and news mentions aliases. Without
an entity graph, memory fragments.

**Tasks.**
- Model company, ticker, CIK, LEI, sector, industry, and people.
- Add aliases and ticker history.
- Resolve `AAPL`, `Apple`, and the CIK to one entity.
- Record merge/split events with provenance.

**Acceptance.**
- Queries resolve at least three alias forms per entity.
- A ticker change does not break history.
- The graph is queryable from the CLI and MCP.

### JAN-017 — Content-addressed dedup and blob store

`area:memory` `type:feature` `priority:P1` `size:M` · **M1** · Depends: JAN-015

**Context.** News and filings duplicate; provenance needs the raw bytes.

**Tasks.**
- Store blobs by SHA-256 on the local filesystem.
- Add canonicalization and exact dedup.
- Add optional near-duplicate detection.
- Add reference counting and a GC policy.

**Acceptance.**
- Identical payloads share one blob.
- Deleting an observation does not orphan an in-use blob.
- Storage metrics are exposed.

### JAN-018 — Source credibility and conflict resolution

`area:memory` `type:feature` `priority:P1` `size:M` · **M1** · Depends: JAN-016, JAN-017

**Context.** Contradictory facts must not overwrite each other. A filing and a
tweet are not the same evidence.

**Tasks.**
- Define source tiers and confidence.
- Record conflicts instead of silently replacing values.
- Implement corroboration and recency rules.
- Allow a human override with provenance.

**Acceptance.**
- A conflict fixture keeps both values and links them.
- The resolution policy is documented and tested.
- Overrides are auditable.

### JAN-019 — Provenance traversal API

`area:memory` `type:feature` `priority:P0` `size:M` · **M1** · Depends: JAN-015, JAN-017

**Context.** Every claim must trace to a source span. This is the difference
between a research tool and a confident guess.

**Tasks.**
- Traverse claim → observation → blob → source span.
- Add a citation formatter.
- Expose the traversal as a CLI command and an MCP resource.
- Test with filings, news, and macro data.

**Acceptance.**
- A demo claim renders a citation with source, timestamp, and hash.
- A missing span is an error, not a silent empty string.
- BeliefBench can consume the traversal.

### JAN-020 — Retention, redaction, and encryption at rest

`area:memory` `area:security` `type:feature` `priority:P1` `size:M` · **M1** · Depends: JAN-015

**Context.** Personal data and licensed content need a lifecycle.

**Tasks.**
- Add retention policies by source and kind.
- Add field-level redaction for personal data.
- Encrypt the database or sensitive columns at rest.
- Add export and delete commands.

**Acceptance.**
- Expired observations are removed by a scheduled job.
- Redaction is tested on a fixture.
- Keys are never stored in the repository.

### JAN-021 — As-of snapshot export / import and corpus lineage

`area:memory` `type:feature` `priority:P1` `size:M` · **M1** · Depends: JAN-015, JAN-017

**Context.** Reproducible research needs frozen snapshots, not a moving database.

**Tasks.**
- Write a snapshot manifest with content hashes and row counts.
- Export observations and features to Parquet plus JSON.
- Import a snapshot into a fresh store.
- Record lineage for BeliefBench.

**Acceptance.**
- Replaying a snapshot produces byte-identical features.
- The manifest detects a tampered file.
- `janus snapshot` is documented.

---

## M2 — Analysis and feature store

### JAN-022 — Indicator engine v1

`area:analysis` `type:feature` `priority:P0` `size:L` · **M2** · Depends: JAN-007, JAN-015

**Context.** Technical features must be deterministic, versioned, and free of
lookahead.

**Tasks.**
- Implement SMA/EMA, RSI, MACD, ATR, Bollinger, OBV, VWAP, and relative strength.
- Add parameter versioning, warmup rules, and a NaN policy.
- Add reference-value tests and no-lookahead tests.
- Document the meaning and failure modes of each indicator.

**Acceptance.**
- Each indicator matches a reference implementation on a fixture.
- A future row cannot change a historical value.
- Parameter changes produce a new feature version.

### JAN-023 — Breadth indicators

`area:analysis` `type:feature` `priority:P0` `size:M` · **M2** · Depends: JAN-022

**Context.** Breadth tells you whether a move is broad or narrow.

**Tasks.**
- Implement advance/decline, % above 50/200 DMA, new highs/lows, McClellan, and
  TRIN.
- Define the universe explicitly.
- Add sector breadth.
- Add fixtures and tests.

**Acceptance.**
- Breadth values match a hand-computed fixture.
- The universe definition is documented.
- The dashboard contract includes breadth.

### JAN-024 — Volatility and regime features

`area:analysis` `type:feature` `priority:P0` `size:M` · **M2** · Depends: JAN-022

**Context.** RSI means different things in a trend and in a range. Regime
features condition every other signal.

**Tasks.**
- Add realized volatility, ATR percentile, VIX term structure, yield curve, and
  credit spread.
- Add a simple HMM or change-point baseline.
- Define regime labels and stability rules.

**Acceptance.**
- Regime labels are stable on a synthetic series.
- The feature set is available as-of.
- Docs explain that regime detection is probabilistic.

### JAN-025 — Sector rotation and relative strength

`area:analysis` `type:feature` `priority:P0` `size:M` · **M2** · Depends: JAN-022, JAN-023

**Context.** The sector dashboard needs relative rotation, not just returns.

**Tasks.**
- Compute 1/3/6/12-month relative returns.
- Compute RRG-style coordinates.
- Add sector breadth and optional flows.
- Add fixtures and tests.

**Acceptance.**
- A known sector fixture produces the expected quadrant.
- The dashboard contract includes rotation data.
- The taxonomy is documented.

### JAN-026 — Fundamentals and event features

`area:analysis` `type:feature` `priority:P1` `size:L` · **M2** · Depends: JAN-009, JAN-016

**Context.** Valuation, growth, revisions, and events are the fundamental side
of the forecast.

**Tasks.**
- Normalize SEC facts into valuation, growth, margin, and cash-flow features.
- Add EPS revisions and guidance flags where available.
- Add event flags: earnings, M&A, litigation, insider trades.
- Attach provenance to every feature.

**Acceptance.**
- A fixture company produces the expected ratios.
- A restated fact is not used in a historical feature.
- Every feature links to a filing.

### JAN-027 — Point-in-time feature store and dashboard contracts

`area:analysis` `type:feature` `priority:P0` `size:L` · **M2** · Depends: JAN-015, JAN-022–JAN-026

**Context.** Features must be reproducible and leak-free, and the UI needs a
stable contract.

**Tasks.**
- Define feature specs, versions, and hashes.
- Materialize features as-of and persist them.
- Add lineage and a feature catalog.
- Define JSON contracts for market, sector, and stock dashboards.
- Add fixtures for each contract.

**Acceptance.**
- The same feature hash is produced across runs.
- A dashboard fixture validates against the schema.
- A missing feature is an explicit error.

---

## M3 — Forecast and review

### JAN-028 — Baseline direction model with calibration

`area:forecast` `type:feature` `priority:P0` `size:M` · **M3** · Depends: JAN-027

**Context.** Start with an honest baseline before anything complex.

**Tasks.**
- Fit a logistic regression on RSI, trend, and breadth.
- Use a time-series split, not a random split.
- Add probability calibration.
- Write a model card with scope and limits.

**Acceptance.**
- Walk-forward output is reproducible.
- Calibration is reported on held-out data.
- No performance claim is made without a stated sample.

### JAN-029 — Quantile and interval forecasts

`area:forecast` `type:feature` `priority:P1` `size:M` · **M3** · Depends: JAN-028

**Context.** A direction probability is not an interval. Users need a range.

**Tasks.**
- Add quantile regression or a GBDT quantile model.
- Produce 10/50/90 quantiles.
- Add coverage tests.
- Document interval width.

**Acceptance.**
- Empirical coverage is within the documented tolerance.
- Intervals widen in high-volatility regimes.
- The ledger stores quantiles.

### JAN-030 — Scenario tree generator

`area:forecast` `type:feature` `priority:P1` `size:M` · **M3** · Depends: JAN-028

**Context.** Markets are conditional. A scenario tree is more honest than a
point forecast.

**Tasks.**
- Define a scenario schema with assumptions and falsifiers.
- Assign probability mass.
- Use the LLM for narrative and deterministic code for numbers.
- Cite evidence for each branch.

**Acceptance.**
- A scenario JSON validates against the schema.
- Probabilities sum to one.
- Every branch has a falsifier.

### JAN-031 — Model registry and feature-hash reproducibility

`area:forecast` `type:feature` `priority:P0` `size:M` · **M3** · Depends: JAN-027, JAN-028

**Context.** A forecast must be reproducible months later.

**Tasks.**
- Store model params, feature hash, data snapshot, and code version.
- Add `janus model list` and `janus model show`.
- Add an artifact store.
- Test replay from the registry.

**Acceptance.**
- Replaying a forecast produces the same probability.
- A missing artifact is an explicit error.
- The registry is documented.

### JAN-032 — Walk-forward backtester

`area:forecast` `type:feature` `priority:P0` `size:L` · **M3** · Depends: JAN-027, JAN-031

**Context.** No honest evaluation without walk-forward, purge/embargo, and
costs.

**Tasks.**
- Implement walk-forward splits with purge and embargo.
- Add transaction costs and slippage.
- Handle delisted names where possible.
- Add metrics and a report.
- Document multiple-testing risk.

**Acceptance.**
- A synthetic leak is detected.
- The same seed produces the same report.
- Costs are explicit, not implicit.

### JAN-033 — Calibration service

`area:forecast` `type:feature` `priority:P0` `size:M` · **M3** · Depends: JAN-028

**Context.** Calibration is the product's core claim.

**Tasks.**
- Add Platt scaling and isotonic regression.
- Compute Brier, log loss, ECE, and reliability curves.
- Slice by regime, horizon, and persona.
- Expose the results to the CLI and dashboard.

**Acceptance.**
- Metrics match a reference fixture.
- A calibrator has a version.
- The dashboard can render a reliability curve.

### JAN-034 — Forecast settlement and outcome resolver

`area:forecast` `type:feature` `priority:P0` `size:M` · **M3** · Depends: JAN-028, JAN-031

**Context.** Predictions must settle automatically, including late data.

**Tasks.**
- Define outcome resolvers for direction, return, and events.
- Use as-of data and idempotent settlement.
- Handle late and missing data.
- Emit an audit record.

**Acceptance.**
- A settled prediction cannot be settled twice.
- Late data is handled without rewriting history.
- The settlement job is tested.

### JAN-035 — Debrief and attribution engine

`area:review` `type:feature` `priority:P1` `size:M` · **M3** · Depends: JAN-034

**Context.** A score without attribution does not teach.

**Tasks.**
- Attribute outcomes to technical, fundamental, macro, sentiment, and luck.
- Decompose contributions.
- Generate lessons and a review object.
- Add a human override.

**Acceptance.**
- A fixture review has a documented attribution.
- Overrides are auditable.
- The CLI can print a debrief.

### JAN-036 — Counterfactual replay

`area:review` `type:feature` `priority:P1` `size:L` · **M3** · Depends: JAN-015, JAN-021, JAN-034

**Context.** The most useful question is "what if we only knew X?"

**Tasks.**
- Replay a decision from an as-of snapshot.
- Swap evidence or persona.
- Diff the forecast and the reasoning.
- Produce a report.

**Acceptance.**
- Replay is deterministic.
- No future data is visible.
- The report explains the delta.

### JAN-037 — Persona-conditioned retrieval and weighting

`area:persona` `type:feature` `priority:P1` `size:M` · **M3** · Depends: JAN-016, JAN-027, JAN-035

**Context.** Taste changes what evidence matters. A value persona and a macro
persona should not rank the same evidence equally.

**Tasks.**
- Map the profile vector to feature weights.
- Condition retrieval ranking.
- Add a prompt/analysis policy.
- Audit the weights used.

**Acceptance.**
- The same evidence produces a different ranked list for two personas.
- The weights are recorded in the review.
- Docs warn against stereotype prompts.

### JAN-038 — Persona tournament

`area:persona` `type:feature` `priority:P1` `size:M` · **M3** · Depends: JAN-037

**Context.** Compare calibration across personas on the same evidence.

**Tasks.**
- Run a tournament over a fixed scenario set.
- Report calibration, hit rate, and drawdown by persona.
- Add a CLI command.
- Prevent cherry-picking.

**Acceptance.**
- The tournament is reproducible.
- Results include confidence intervals.
- The report is published with the sample.

### JAN-039 — AgentDescent persona evolution

`area:persona` `type:research` `priority:P2` `size:L` · **M3** · Depends: JAN-038

**Context.** The persona should improve with outcomes, under a held-out gate.

**Tasks.**
- Integrate AgentDescent as an optional dependency.
- Define a fitness function on walk-forward outcomes.
- Keep a held-out time split.
- Version every evolved persona.
- Add a safety gate.

**Acceptance.**
- An evolution run is reproducible.
- No persona is promoted without held-out evidence.
- The artifact is versioned and auditable.

---

## M4 — Interface

### JAN-040 — MCP server v1

`area:interface` `type:feature` `priority:P0` `size:L` · **M4** · Depends: JAN-019, JAN-027, JAN-033

**Context.** The core must be reachable from Claude, ChatGPT, OpenCode, Cursor,
and DSH.

**Tasks.**
- Expose resources for market, sector, stock, thesis, and calibration.
- Expose tools for as-of query, forecast creation, and debrief.
- Add auth and error handling.
- Document the tool contracts.

**Acceptance.**
- MCP Inspector can list and call the tools.
- Errors are typed and actionable.
- The docs include a minimal client example.

### JAN-041 — DSH market / sector / stock panels

`area:interface` `type:feature` `priority:P0` `size:L` · **M4** · Depends: JAN-027, JAN-040

**Context.** The shell needs dashboards, not a chat box.

**Tasks.**
- Implement the three panels against the dashboard contracts.
- Add loading, empty, and error states.
- Add a fixture mode.
- Document the panel API.

**Acceptance.**
- DSH renders all three panels with fixture data.
- A missing feature shows an explicit error.
- The demo uses the real MCP server.

### JAN-042 — DSH commands, daily brief, and cron

`area:interface` `type:feature` `priority:P0` `size:M` · **M4** · Depends: JAN-041

**Context.** Daily use needs a brief and a schedule.

**Tasks.**
- Add `/janus brief`, `/janus market`, `/janus forecast`, `/janus review`.
- Implement a daily brief template with citations.
- Add a cron job with a timezone.
- Add approval for sharing.

**Acceptance.**
- A scheduled brief runs end to end.
- The brief cites sources and as-of time.
- The cron job is configurable and tested.

### JAN-043 — Approvals and signed sharing

`area:interface` `area:security` `type:feature` `priority:P1` `size:M` · **M4** · Depends: JAN-042

**Context.** Sharing a forecast or thesis needs consent and provenance.

**Tasks.**
- Add an approval card before sharing.
- Sign the shared payload with the bot-social identity.
- Include the as-of snapshot hash.
- Add an audit entry.

**Acceptance.**
- A shared payload is signed and verifiable.
- Rejection leaves no shared artifact.
- The audit log records the decision.

### JAN-044 — CLI UX v1

`area:interface` `type:feature` `priority:P1` `size:M` · **M4** · Depends: JAN-040

**Context.** Local-first users need a scriptable CLI.

**Tasks.**
- Add `janus brief`, `forecast`, `review`, `persona`, and `snapshot`.
- Add `--json` output.
- Add shell completion.
- Document examples.

**Acceptance.**
- Every command has a help page and a test.
- JSON output is stable.
- The CLI works without DSH.

---

## M5 — Evaluation, security, and release

### JAN-045 — BeliefBench scenario schema and loader

`area:eval` `type:feature` `priority:P0` `size:M` · **M5** · Depends: JAN-019, JAN-021

**Context.** Evaluation needs historical as-of scenarios with resolutions.

**Tasks.**
- Define the scenario schema: entity, as_of, question, resolution, tags.
- Add a loader and validation.
- Add a sample set of 100 scenarios.
- Document how to contribute a scenario.

**Acceptance.**
- The sample set loads and validates.
- Every scenario has a resolution date and evidence.
- The schema is versioned.

### JAN-046 — BeliefBench runner and as-of guard

`area:eval` `type:feature` `priority:P0` `size:M` · **M5** · Depends: JAN-045

**Context.** Running an evaluation must be as-of-safe by construction.

**Tasks.**
- Run scenarios through the core.
- Enforce the as-of guard and fail closed.
- Capture evidence and forecasts.
- Produce a report.

**Acceptance.**
- A future-dated scenario fails the run.
- The report includes evidence and citations.
- The run is deterministic.

### JAN-047 — Evaluation metrics suite

`area:eval` `type:feature` `priority:P0` `size:M` · **M5** · Depends: JAN-046

**Context.** Claims need comparable metrics.

**Tasks.**
- Add Brier, log loss, ECE, reliability, directional accuracy, regime latency,
  citation accuracy, and interval coverage.
- Add slices by regime, horizon, and persona.
- Add a report writer.

**Acceptance.**
- Metrics match a reference fixture.
- Every metric has a documented definition.
- The report is reproducible.

### JAN-048 — Baselines and reproducible benchmark report

`area:eval` `type:test` `priority:P0` `size:M` · **M5** · Depends: JAN-047

**Context.** A number without a baseline is marketing.

**Tasks.**
- Add random, always-up, RSI-only, and buy-and-hold baselines.
- Add seeds and a report template.
- Run in CI on a small fixture.
- Publish the sample and the limitations.

**Acceptance.**
- The report is reproducible from a clean checkout.
- Baselines are reported alongside Janus.
- No cherry-picked sample is used.

### JAN-049 — Secrets, data licensing, and ToS policy

`area:security` `type:task` `priority:P0` `size:S` · **M5** · Depends: —

**Context.** Free data is not free of terms. Secrets must never leak.

**Tasks.**
- Add secret scanning and a pre-commit hook.
- Maintain a data source registry with ToS and attribution.
- Document what may not be redistributed.
- Add a CI check.

**Acceptance.**
- CI fails on a committed key.
- The registry lists every default source.
- The docs explain the redistribution policy.

### JAN-050 — Compliance copy, disclaimers, China guardrails

`area:security` `area:docs` `type:docs` `priority:P0` `size:S` · **M5** · Depends: —

**Context.** Janus is research tooling, not investment advice. In China,
securities investment advisory requires a license.

**Tasks.**
- Put the disclaimer in README, CLI, and the UI.
- Ban buy/sell language and return promises in copy.
- Add a forbidden-phrase test.
- Document the China positioning and the need for legal review.

**Acceptance.**
- The disclaimer appears in all user-facing surfaces.
- The forbidden-phrase test passes.
- The docs state that this is not legal advice.

---

## Suggested first ten

If the goal is a credible V1 with the least thrash:

1. JAN-001 contracts
2. JAN-002 migrations
3. JAN-003 config
4. JAN-005 as-of property tests
5. JAN-015 bitemporal query hardening
6. JAN-007 Tiingo
7. JAN-009 SEC EDGAR
8. JAN-022 indicators
9. JAN-027 feature store
10. JAN-028 baseline forecast

These give a working spine: data → memory → features → forecast, with tests that
make the rest safe to build.
