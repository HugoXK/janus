# 0005 — Tamper-evident audit chain

- Status: accepted
- Date: 2026-11-28
- Decision owner: Janus Dev Lead (implementation: Janus Dev 3)
- Issue: #156 (JAN-148)
- Supersedes: the "hash chain not in scope" note in
  `docs/SECURITY-THREAT-MODEL.md`

## Context

`PredictionLedger` is append-only by API: there is no update or delete method
for a prediction, and settlement only attaches an outcome. That is a
programming property, not a storage guarantee. The threat model already listed
"direct SQLite edits by the same user are undetectable" as a residual risk, and
JAN-148 asks for a tamper-evident ledger with verification and exportable
checkpoints across predictions, outcomes, shares and overrides.

The constraint is local-first, single-user, no key management, and a free core
path. A signature scheme would need key storage, rotation and recovery that the
project does not have, and any key stored next to the database adds little
against an actor who can already write both.

## Decision

Add a SHA-256 hash chain (`audit_entry`, migration 9) and append to it from
`PredictionLedger.record` and `PredictionLedger.settle`; expose
`AuditChain.record_share` / `record_override` for the sharing and approval
surfaces. Verification recomputes the chain and compares audited payloads with
live rows, raising typed errors (`ChainGapError`, `EntryHashError`,
`SourceDriftError`, `SourceMissingError`, `CheckpointMismatchError`). Add
append-only SQLite triggers as defence in depth, and make checkpoints exportable
(`janus audit export`) so an external copy detects tail truncation.

## Alternatives considered

- **HMAC signature with a local key.** Rejected for now: key storage, rotation
  and recovery are a separate security project; a key in the same directory
  does not raise the bar against the same OS user.
- **Merkle batches instead of a linear chain.** Better for very large logs and
  partial proofs, but adds tree bookkeeping for a single-writer local store. The
  linear chain is enough for O(n) verification and checkpoint export.
- **External timestamping / transparency log.** The right long-term anchor for
  third-party verifiability; out of scope for a free, offline core path.
- **Database encryption only.** Detects nothing; it hides content but does not
  detect a rewritten row.
- **A boolean `verify()` only.** Rejected: JAN-148 requires an explicit failure
  state, so failures are typed exceptions with the offending sequence number.

## Consequences

- Every ledger write appends one row; verification and export are O(n).
- A deleted middle row, a rewritten entry, a rewritten prediction/outcome, and
  a moved settlement pointer are detected.
- Deleting the newest rows is only detected when an external checkpoint is
  available. This is documented, not hidden.
- Pre-migration rows are not hashed retroactively; verification only covers
  entries that exist.
- `outcome_id` is excluded from the prediction payload because settlement is the
  one allowed mutation; the outcome entry checks the back-pointer instead.

## Reopen triggers

- A sharing surface (JAN-043) needs recipient-verifiable bundles: add a signed
  checkpoint or an HMAC key with an explicit key-management ADR.
- More than one writer process, or a hosted deployment: revisit Merkle batching
  and transactionally coupled writes.
- An audit requirement for third-party proof of time: anchor checkpoints in an
  external transparency log.
