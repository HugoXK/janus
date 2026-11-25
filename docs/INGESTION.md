# Ingestion

The ingestion layer is a set of adapters plus a scheduler, a dead-letter queue,
and post-ingest quality checks. Every observation keeps its source, raw hash, and
publication time.

## Adapters

| Adapter | Input | Notes |
| --- | --- | --- |
| `TiingoSource` | EOD prices | API key, cache, rate limit |
| `YFinanceSource` | Yahoo prices | Unofficial fallback |
| `SECEdgarSource` | Filings and XBRL | Authoritative, as-filed facts |
| `FREDSource` | Macro series | ALFRED vintages |
| `GDELTSource` | Global news articles | Noisy, exact-URL dedup |
| `RSSSource` | RSS 2.0 / Atom | TTL cache, canonical URL dedup |

Adapters return `Observation` objects. They never write to the store directly;
the scheduler owns persistence.

## Scheduler

```python
from janus.data import GDELTSource, IngestionScheduler

result = IngestionScheduler(store, retries=3, max_concurrency=4).run(
    GDELTSource(),
    ["ACME", "BETA"],
    start,
    end,
)
print(result.fetched, result.stored, result.failed, result.dead_letters)
```

- `max_concurrency` bounds how many `source.fetch` calls run at once and
  defaults to `1`, which keeps the sequential path. Values below 1 are rejected
  by the constructor.
- Only fetching is pooled. Every store write happens on the thread that called
  `run`, after collection, in input entity order, because the SQLite connection
  is single-threaded. Row order and dead-letter order therefore never depend on
  which fetch finishes first; a pooled run holds one run's observations in
  memory until collection ends.
- Persistence still commits row by row on one connection, so a higher limit
  shortens wall time only as far as fetching is the bottleneck. It is a bound on
  in-flight provider calls, not a throughput promise.
- Retries use exponential backoff, and an entity's attempts stay sequential
  even when other entities fetch in parallel.
- Exhausted entities go to `ingestion_dead_letter`; `replay` retries them and
  stamps `replayed_at`.
- `ingestion_run` records status and counts for each run. A failing entity makes
  the status `partial`; a store error still aborts the run.

## Quality checks

```python
from janus.data.quality import check_observations

report = check_observations(observations, as_of=as_of, max_age_days=7)
if not report.ok:
    raise RuntimeError([issue.code for issue in report.errors])
```

Current checks:

- duplicate observation ids (`error`);
- missing source or `raw_hash` (`error`);
- future `published_at` (`error`);
- non-positive close (`error`);
- missing numeric close (`warning`);
- stale price feed (`warning`).

The checks fail closed on provenance and price errors. Feed the report into the
daily brief or the scheduler run report.

## Point-in-time rules

- Store `published_at` (when the world could know) and `observed_at` (when we
  ingested).
- Never fill a missing price with a later value.
- For macro, prefer ALFRED vintages.
- For filings, keep as-filed facts and do not overwrite them with restatements.

## Tests

- `tests/test_gdelt.py`
- `tests/test_rss.py`
- `tests/test_scheduler.py`
- `tests/test_quality.py`
