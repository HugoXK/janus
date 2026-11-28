# Tamper-evident audit chain

Janus records what it believed before an outcome was known. The audit chain is
the second lock on that record: every prediction, settled outcome, share and
override can be committed to an append-only SHA-256 hash chain, and a later
verification detects a deleted row, a rewritten row, or a settlement pointer
that was moved to another outcome.

It is research tooling. It is not advice and it is not a trading or execution
path.

## What is chained

| Kind | Written by | Source checked on verify |
| --- | --- | --- |
| `prediction` | `PredictionLedger.record` | `prediction` row (immutable fields; `outcome_id` excluded) |
| `outcome` | `PredictionLedger.settle` | `outcome` row plus the `prediction.outcome_id` back-pointer |
| `share` | `AuditChain.record_share` (JAN-043 boundary) | audited payload only |
| `override` | `AuditChain.record_override` | audited payload only |

Each entry stores `seq`, `kind`, `ref_id`, `recorded_at`, a canonical JSON
payload, `prev_hash` and `entry_hash`. `entry_hash` is SHA-256 over the six fields `seq`, `kind`, `ref_id`,
`recorded_at`, `prev_hash`, `payload_json`, each framed as
`<length>:<value>` and concatenated (no delimiter can be forged by a field
value). `payload_json` is compact, key-sorted JSON (`sort_keys=True`,
separators `(",", ":")`). The first entry links to `GENESIS = "0" * 64`.

## Verification

```sh
janus audit verify --db ~/.janus/janus.db
janus audit export --out audit-2026-11-28.json
janus audit verify --db ~/.janus/janus.db --checkpoint audit-2026-11-28.json
```

`verify` recomputes every hash, checks sequence continuity, and compares each
chained source row with the payload that was audited. `--require-complete` also
scans `prediction` and `outcome` for rows that have no audit entry. Failures are typed
exceptions, not a boolean:

| Error | Meaning |
| --- | --- |
| `ChainGapError` | a sequence number is missing: a row was deleted |
| `EntryHashError` | a stored entry no longer matches its recomputed hash, or the chain does not link |
| `SourceDriftError` | the live prediction/outcome row (or settlement pointer) differs from the audited payload |
| `SourceMissingError` | an audited source row was deleted |
| `CheckpointMismatchError` | the chain no longer matches an exported checkpoint, e.g. the newest rows were truncated |

`AuditChain.verify_export(path)` verifies an exported file offline, without a
store. It proves internal consistency of the file and its checkpoint; it cannot
compare against live rows.

## as-of and version story

- `recorded_at` is normalized to UTC and is the time Janus appended the event.
  Predictions use the prediction's `created_at`; outcomes use append time.
- `AuditChain.entries(as_of=...)` and `checkpoint(as_of=...)` return a
  **contiguous** prefix: they stop at the first entry recorded after `as_of`.
  Ordering is sequence order, not timestamp order, so a backdated entry cannot
  punch a gap into an exported prefix. A backdated entry appended after the
  stopping point is excluded until the next export.
- The export carries `"version": 1`; `verify_export` rejects unknown versions.
- The chain lives in schema migration **9** (`audit_chain`). Databases created
  before it are migrated on first open; pre-existing rows are not retroactively
  hashed.

## Determinism

For a fixed `(seq, kind, ref_id, recorded_at, payload, prev_hash)` the hash is
byte-identical across runs and machines. Payloads are canonicalized before
hashing and storage, so dict ordering does not matter. The audit entries of the
same event sequence verify to the same head hash; the chain does not depend on
wall-clock ordering.

## Limits (read before relying on it)

- **No signature.** The chain proves internal consistency. A process that can
  write the SQLite file can also drop the triggers and rewrite history; it
  would have to rewrite every following entry to keep verification green, which
  is detectable once a checkpoint exists outside that process.
- **Tail truncation needs an external checkpoint.** Deleting the newest rows
  leaves a shorter, self-consistent chain. Export a checkpoint on a schedule and
  pass it back with `--checkpoint`.
- **Not encryption.** The store is still plaintext and readable by the same OS
  user. The chain detects modification, not disclosure.
- **Observations, theses and reviews are not chained.** Only the four kinds
  above are in scope for JAN-148.
- **Rows written around the ledger API are not chained.** The ledger writes the
  source row and its audit entry in one transaction, so a failed append rolls
  back both. But a direct `INSERT` through the store, or a row that predates
  migration 9, has no entry; a plain `verify` checks chained rows, not
  completeness. Use `--require-complete` when the store is expected to contain
  only ledger-written rows.
- **Append-only triggers are defence in depth**, not a security boundary. They
  stop accidental updates and deletes; they do not stop an actor who can run
  arbitrary SQL.

## Operational cost

Verification is O(n) in the number of chained entries: one hash per entry plus
one indexed read of the source row for predictions and outcomes.
`--require-complete` adds one full scan of `prediction` and `outcome`. Exports are
proportional to the prefix size. There is no background job; run
`janus audit verify` after a settlement batch, and export a checkpoint before
long-running research, backups, or sharing a bundle.

## Python surface

```python
from janus.forecast.ledger import PredictionLedger
from janus.memory.audit import AuditChain

ledger = PredictionLedger(store)      # appends prediction/outcome entries
chain = AuditChain(store)
report = chain.verify()               # raises typed errors
checkpoint = chain.export("audit.json")
```

`record_share` and `record_override` are the audit boundary for the sharing and
approval surfaces; they accept a `ref_id` and a JSON payload, so they do not
depend on JAN-043 shipping first.
