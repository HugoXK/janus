# Data model

The central rule: **an observation is only visible if it was published and valid
at the requested `as_of` time.**

## Schema version and migrations

- `SCHEMA_VERSION` lives in `core/janus/contracts.py`; currently `5`.
- `schemas/janus.schema.json` is the checked-in contract. `janus schema check`
  fails if it drifts from the Pydantic models.
- Migrations live in `core/janus/memory/migrations.py`. The `schema_migrations`
  table records applied versions; `janus migrate --dry-run` lists what would run.
- Compatibility policy: additive fields are allowed within a version; renames
  and removals require a new version and a migration. No silent data loss.
- All timestamps are timezone-aware and normalized to UTC by `UtcModel`; naive
  timestamps are rejected at validation time.

## Tables

### `observation`

| Column | Meaning |
| --- | --- |
| `published_at` | When the world could have known it |
| `observed_at` | When Janus ingested it |
| `valid_from` / `valid_to` | The fact's own validity window |
| `source` | Provider or document |
| `raw_hash` | Content hash for provenance |
| `value` | JSON payload (close, EPS, headline, ...) |
| `confidence` | Optional extraction confidence |

### `thesis`

A belief with explicit assumptions, catalysts, risks, and falsifiers. A thesis
is not a prediction; it is the reasoning that predictions test.

### `prediction`

An ex-ante forecast. It is immutable once written. The only allowed mutation is
attaching an `outcome_id` after the outcome is known.

### `outcome`

The ex-post realization, with its source and optional score.

### `persona`

A structured taste profile: dimension vector, feature weights, rules, and
version. Personas are priors, not prompt role-play.

### `review`

A debrief: attribution weights, calibration, and lessons.

### `feature_value`

Point-in-time materialized features. The primary key is
`(entity_id, as_of, name, version)`. Reads return the latest materialization at
or before the requested time, so a later restatement cannot leak into an earlier
view. `features_hash` identifies the vector; `source_hash` points at the input
snapshot.

### `ingestion_run` / `ingestion_dead_letter`

`ingestion_run` records one scheduler run: source, start/finish, status, counts.
`ingestion_dead_letter` records an entity that exhausted its retries; `replay`
stamps `replayed_at` after a successful retry.

### Model artifacts (files)

Fitted models are not rows. `ModelRegistry` writes one canonical JSON document
per artifact to `$JANUS_HOME/models/<artifact_id>.json`, named by the SHA-256 of
its content (`created_at` excluded). The document records the model card and
parameters, the feature values and hash, the data snapshot, and the code
version. Predictions reference an artifact through the existing `model_version`
column using the `version@<artifact_id[:12]>` convention; no table or migration
is added. See `docs/FORECASTING.md` for replay rules.

## Retention and redaction

`core/janus/memory/retention.py` applies source/kind retention windows and
deletes only observations whose expiration is at or before `as_of`; a dry run
reports the same counts without writing. `redact_value` masks named fields at
any depth, and `export_redacted` writes JSONL without mutating stored facts.
The CLI exposes `janus retention apply` and `janus retention export`.

## As-of semantics

There are two questions, and two modes:

| Mode | Question | Time column |
| --- | --- | --- |
| `published` | What could the world have known? | `published_at <= as_of` |
| `observed` | What had this system actually ingested? | `observed_at <= as_of` |

Both modes respect the fact's validity window:

```sql
SELECT * FROM observation
WHERE entity_id = ?
  AND <time_column> <= :as_of
  AND (valid_from IS NULL OR valid_from <= :as_of)
  AND (valid_to IS NULL OR valid_to > :as_of)
  AND (:snapshot_id IS NULL OR snapshot_id = :snapshot_id)
ORDER BY <time_column> ASC, id ASC
LIMIT :limit OFFSET :offset;
```

Future rows may exist in the database; they are simply excluded. `test_asof.py`
is the guardrail, and `test_asof_hypothesis.py` generates adversarial windows.

The `observed` mode is intentionally different: it can include a row whose
publication timestamp is in the future if the system ingested it early. That is
a data-quality anomaly, not a license to use future knowledge; the published
mode remains the default.

## Immutability

- `observation` uses `INSERT OR REPLACE` for safe re-ingestion.
- `thesis` status may change; the original statement and falsifiers stay.
- `prediction` has one mutation path: `attach_outcome`.
- `outcome` and `review` are append-only.

## Why three timestamps

Using only `fetched_at` creates lookahead bias: a backtest would see data that
was ingested later but not available at the simulated decision time. Using only
`published_at` loses ingestion reality. Keeping both lets you answer two
different questions:

- What could have been known at time T? (`published_at <= T`)
- What did this system actually know at time T? (`observed_at <= T`)
