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

### `share_request` / `share_audit`

`share_request` stores a pending, approved, or rejected share payload with its
`as_of`, snapshot hash, requester, approver, and signed envelope. The envelope
is bound to the request id and records the approver and approval time inside the
signature. `share_audit` is append-only: database triggers reject UPDATE and
DELETE, and every request, approval, and rejection records an actor and
timestamp. Migration v12 adds both tables.

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

## Source tiers and conflicts

`core/janus/memory/conflicts.py` resolves competing observations only when both
carry an explicit `fact`/`metric`/`field` key. The policy is ordered: source
tier, observation confidence, corroborating-value count, then publication time.
Source prefixes are matched case-insensitively and treat `-` and `_` alike.
Both values stay in the report; a tie or a same-tier/same-time disagreement is
explicitly `unresolved`. Human overrides are appended to a JSONL audit with the
actor, reason, selected id, alternatives, and timestamp, never overwriting the
original observations. Override files are single-writer: appends are not locked,
so concurrent writers are unsupported, and readers skip unparseable lines and
report how many were skipped. If the recorded selection no longer belongs to the
rebuilt conflict group (for example after a restatement), the override is
reported as `stale` with `selected_id=None` rather than re-pointing the group at
a dangling observation.
## Security master and universe membership

`security` stores symbol/exchange/share-class rows with `valid_from`/`valid_to`;
the same symbol can belong to different entities in different windows.
`universe_membership` stores point-in-time index membership and joins to the
security row. `SecurityMaster.resolve()` and `members()` filter both windows, so
a universe query cannot include a delisted or not-yet-listed name. Migration v6
adds both tables.

## Corporate actions

`corporate_action` stores splits, stock/cash dividends, mergers, spin-offs, and
symbol changes with `effective_at`, source, raw hash, and payload. The ledger
returns an explicit adjustment basis: split factors and cash dividends are
applied deterministically, while merger/spin-off/symbol-change rows are flagged
as manual actions rather than silently applied. Migration v7 adds the table.

## Source spans

`source_span` stores an exact locator (`page=12;paragraph=3`, table cell, etc.),
excerpt, optional byte offsets, and a blob hash tied to an observation.
`SpanStore.citation()` refuses a missing span and returns a citation containing
source, published time, URI/hash, locator, and excerpt hash. Migration v8 adds
the table.

## Snapshot archives

`core/janus/memory/snapshot_archive.py` exports an as-of freeze as
`manifest.json` plus `observations.json` and `features.json` (and Parquet when
an optional writer is available). The manifest records row counts, per-file
SHA-256 hashes, lineage, and a content hash. `verify_snapshot` detects tampering
or missing files before `import_snapshot` writes into a fresh store. The CLI
exposes `janus archive export/verify/import`.

## Retention and redaction

`core/janus/memory/retention.py` applies source/kind retention windows and
deletes only observations whose expiration is at or before `as_of`; a dry run
reports the same counts without writing and sets `dry_run` on the result.
Rules are evaluated in order and the **first match wins**, so a broad rule
(`*:*:365`) placed first shadows every specific rule after it. `redact_value`
masks named fields at any depth — top-level columns as well as nested keys in
`value` — and `export_redacted` writes JSONL without mutating stored facts. The
CLI exposes `janus retention apply` and `janus retention export`; both reject a
naive `--as-of` so a destructive cutoff cannot silently use the host time zone.

Retention deletes observation rows but leaves their content-addressed blobs on
disk. Run `janus blob gc` afterwards when the raw documents were meant to age
out as well.
## Maintenance

`core/janus/memory/maintenance.py` wraps `PRAGMA integrity_check`,
`PRAGMA foreign_key_check`, the SQLite backup API, `VACUUM`, and per-table row
counts. The CLI exposes `janus db check|backup|vacuum|stats`; backups are written
through SQLite's online backup API so the copy is consistent.

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

## Encryption at rest

Free-text columns in `thesis` (`statement`, `assumptions`, `catalysts`,
`risks`, `falsifiers`), `prediction.target` and `outcome.realized_value` are
sealed with AES-256-GCM under the data key named by the row's `key_id`. The data
key is wrapped by the master key (KEK) and stored in `encryption_key`;
`key_id IS NULL` means the row predates migration. Rotation progress lives in
`encryption_rotation(target, last_rowid)`, so an interrupted rotation resumes.
Ids, timestamps, statuses, numbers and hashes stay plaintext, which keeps `as_of`
filtering, ordering and pagination independent of ciphertext. Each ciphertext is
bound to `<table>.<column>:<row id>`, so a value moved to another column or row
fails authentication. Blobs stay content-addressed by the plaintext SHA-256
(`raw_hash`/`raw_uri` unchanged) while their contents are sealed. Full key
hierarchy, migration and recovery: `docs/adr/0005-encryption-at-rest.md`.

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
