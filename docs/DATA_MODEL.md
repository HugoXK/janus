# Data model

The central rule: **an observation is only visible if it was published and valid
at the requested `as_of` time.**

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

## As-of semantics

```sql
SELECT * FROM observation
WHERE entity_id = ?
  AND published_at <= :as_of
  AND (valid_from IS NULL OR valid_from <= :as_of)
  AND (valid_to IS NULL OR valid_to > :as_of)
ORDER BY published_at ASC;
```

Future rows may exist in the database; they are simply excluded. `test_asof.py`
is the guardrail.

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
