# ADR 0005: Encryption at rest with a KEK/DEK envelope

## Status

Accepted, 2026-11-28. Implements JAN-147 / issue #155.

## Context

The SQLite store kept free-text research (`thesis.statement` and its lists,
`prediction.target`, `outcome.realized_value`) in plaintext, and the blob store
kept raw source documents (filings, transcripts, licensed payloads) as plaintext
under `<root>/<aa>/<sha256>`. A copied database, a blob directory, a disk image
or a synced backup disclosed all of it. The store already records `raw_hash` and
`raw_uri` per observation, and content addressing is what makes deduplication
and provenance work, so encryption must change neither the digest nor the path.

Constraints:

- local-first, no KMS/HSM, no paid service;
- `as_of` queries, ordering and pagination must keep their semantics;
- a missing, wrong or corrupted key is an explicit typed error, never an empty
  value, skipped row, or plaintext fallback;
- key material never lives in the repository, the database (unwrapped), a log,
  an error message, or an MCP response.

## Decision

**Hierarchy (envelope).**

```
KEK  (JANUS_MASTER_KEY env, or 0600 file: JANUS_MASTER_KEY_FILE,
      default $JANUS_HOME/keys/master.key)
 └── DEK per key_id, wrapped by the KEK, stored in encryption_key(key_id,
     wrapped_dek, state, created_at, retired_at)
      └── field ciphertext  janus1.<key_id>.<nonce>.<ciphertext+tag>
```

- The KEK is only ever read from `JANUS_MASTER_KEY` or a `0600` file. A file
  with group/world permission bits is rejected (`key_invalid`).
- DEKs are 32 random bytes, stored only wrapped
  (`januswrap1.<nonce>.<ciphertext+tag>`) in the store. The store never holds an
  unwrapped DEK on disk.
- Each encrypted record carries `key_id`; a wrong or unknown key id is
  `key_mismatch`, and tampering or a context swap is `ciphertext_invalid`.

**Encrypted columns** (`encrypted_columns()` in `memory/encryption.py`):

| Table | Column(s) |
| --- | --- |
| `thesis` | `statement`, `assumptions`, `catalysts`, `risks`, `falsifiers` |
| `prediction` | `target` |
| `outcome` | `realized_value` |

Every other column (ids, timestamps, confidence, hashes, status, prices) stays
plaintext so `as_of` filtering, ordering and pagination do not depend on
ciphertext. `observation` values, `feature_value`, `review` and model artifacts
stay plaintext in this slice; that is the documented boundary, not a claim of
full-database encryption (follow-up issue).

**Bind to a location.** Additional authenticated data is
`janus1|<table>.<column>:<row id>`, so moving a ciphertext between columns or
rows fails authentication instead of decrypting the wrong value.

**Fail closed.** Opening a store that has keys without a master key raises
`key_missing`; a master key that cannot unwrap the active DEK raises
`key_mismatch` at open time. Reads and CLI commands exit non-zero with
`error [<code>]: …`. A plaintext store remains openable without keys until it is
migrated, so `janus demo` and the test suite keep working on a fresh store.

**Rotation** (`janus keys rotate`, resumable):

1. create a new active `key_id` (`k1`, `k2`, …); the previous key becomes
   `retired` but stays for decryption;
2. re-encrypt rows batch by batch (default 100 rows), persisting
   `encryption_rotation(target, last_rowid)` per table and committing per batch;
3. an interrupted run resumes with the same key id; completed rows are skipped
   because their `key_id` already matches;
4. blobs are re-wrapped file by file under the same active key;
5. `janus keys retire --key-id K` deletes the old key only when no row or blob
   references it (`key_in_use` otherwise).

**Migration from plaintext v0.1** (`janus keys migrate`):

1. count plaintext rows and blobs; when there are none the command is a no-op
   and creates no backup;
2. otherwise copy the database with SQLite's backup API to
   `<db>.pre-encryption-<UTC>.bak` (`0600`, never overwritten);
3. encrypt rows in batches, then migrate plaintext blobs;
4. any failure restores the backup and re-raises, so the database is left
   exactly as it was;
5. re-running after success is a no-op.

**Blob store.** `EncryptedBlobStore` keeps the path
`<root>/<aa>/<sha256(plaintext)>`, so `raw_hash`, `raw_uri`, dedup and
provenance are unchanged; only the file contents become envelopes. Reads of
legacy plaintext files fail closed (`plaintext_blob`) until migrated.

**Config redaction.** The master key is never loaded into `Settings`, so
`janus config show`/`config doctor` cannot print it; a test asserts the value
does not appear in CLI output.

## Options considered

| Option | Cost | Risk | Rollback | Why not |
| --- | --- | --- | --- | --- |
| SQLCipher / full-file encryption | Native dependency; whole-file key; changes the sqlite3 contract | Breaks standard tooling and the as-of fixtures | Restore plaintext DB | Larger blast radius than the listed payloads; hides access patterns without protecting metadata better |
| Encrypt `observation.value` too | Every read path and `LIKE` search; full-table migration | Breaks search and the as-of property fixtures | Decrypt rows | Deferred as a follow-up; documented boundary |
| KEK/DEK envelope on listed fields + blobs (chosen) | One declared dependency, one migration | Derived values stay plaintext | Keep old key ids; revert PR | Narrow, testable, keeps as-of and provenance untouched |

## Consequences

Good:

- Copied stores, blob directories, disk images and backups no longer disclose
  the listed free text or raw documents.
- Rotation is decoupled from content and provenance; a key can be retired one id
  at a time, and interrupted rotation resumes.
- Failures are typed and explicit; nothing silently degrades to plaintext.

Bad / accepted:

- `observation` values, features, reviews and model artifacts remain plaintext.
  This is recorded as residual risk.
- Losing every copy of the KEK makes encrypted data unrecoverable. There is no
  escrow and no recovery path on purpose; the docs say so.
- The KEK is available to the process environment; encryption protects at-rest
  copies, not a compromised host or process.
- Rotation is O(rows + blobs); each file is replaced atomically, but the whole
  operation is not a single transaction, so an interrupted run leaves a mix of
  key ids that `janus keys status` reports.
- Migration takes a full copy of the database first, so it needs that much free
  disk and exclusive-ish access while it runs.

## Operational runbook

```sh
# one-time
export JANUS_MASTER_KEY="$(base64 < 32-random-bytes)"   # or point at a 0600 file
janus keys init    --db ~/.janus/janus.db
janus keys migrate --db ~/.janus/janus.db --blob-root ~/.janus/blobs

# rotation after exposure or on schedule
janus keys rotate  --db ~/.janus/janus.db --blob-root ~/.janus/blobs
janus keys status  --db ~/.janus/janus.db --blob-root ~/.janus/blobs
janus keys retire  --db ~/.janus/janus.db --key-id k1
```

`janus keys status` is the health check: non-zero `plaintext_rows` means a
migration is pending, a retired id that still appears in `rows`/blobs means a
rotation is pending, and `rotation_in_progress` means a run was interrupted and
the next `janus keys rotate` continues it.

## Revisit trigger

- `observation` or feature values start holding licensed or personal payloads.
- Server mode / multi-tenancy (JAN-145) needs per-tenant keys.
- An OS keychain or TPM-backed KEK becomes a requirement.
- Full-database encryption is requested for compliance rather than payload
  protection.
