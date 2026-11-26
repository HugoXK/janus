# Security threat model

Janus is local-first research software. It does not execute trades, holds no
broker credentials, and has no network service listening for inbound
connections. This document covers the three surfaces that do exist — the MCP
boundary, local data at rest, and the sharing/approval surface — and states
honestly which controls are live today.

**Status vocabulary.** Every row uses exactly one of:

- `implemented` — the control exists in shipped code and is exercised.
- `partial` — a control exists but does not cover the whole threat.
- `planned` — designed or backlogged, **not** shipped, protects nothing today.
- `not implemented` — no control exists.

`Status` reflects the code at the base this document was written against
(`12cd78c0`). A planned control is never described as preventing anything.
The sharing surface is a baseline HMAC implementation (JAN-043): approval is
explicit, the envelope is signed, and decisions are audited. It is not a
cross-party asymmetric identity system.

## Surface: MCP tools and resources

`core/janus/mcp/server.py` wraps `core/janus/mcp/service.py` in a `FastMCP`
server (`server.py:11-23`) launched over stdio (`server.py:231-236`). Eleven
tools are registered (`server.py:26-38`), ten of them touching the store; six
resources are read-only (`docs/MCP.md:22-52`).

| Threat | Impact | Mitigation | Status | Residual risk |
| --- | --- | --- | --- | --- |
| Any local process can call every MCP tool: the server has no authentication or authorization | Full read/write of the local store through the tool boundary; an actor can record theses and forecasts as the user | None beyond the OS user and process boundary; the server is stdio `FastMCP` with no token check (the JAN-040 auth task is pending) | not implemented | Any process running as the same OS user can invoke write tools |
| Arbitrary file read through `janus_beliefbench_run`'s `scenarios_path` argument | Read any file the process can open | The resolved path must equal, or sit below, the configured `scenarios_root` (`service.py:172-176`) | implemented | The root defaults to the working directory, so any file below it is loadable; there is no size or schema limit on the scenario file |
| Write tools (`janus_thesis_create`, `janus_forecast_create`, `janus_forecast_settle`, `janus_review_debrief`) mutate the store without authorization | Forged or deleted research history | The tool surface is explicit and resources are read-only (`docs/MCP.md:44-52`); there is no per-caller authorization | partial | Same OS-user boundary as above; no audit log of tool calls |
| Ledger tampering: a recorded forecast is meant to be immutable | Ex-post rewriting of predictions would destroy calibration evidence | The API has no update or delete path for a prediction; settlement only attaches an outcome (`core/janus/forecast/ledger.py:11-17`, `memory/store.py:292-297`) | partial | No database trigger, hash chain, or signature; direct SQLite edits by the same user are undetectable |
| Resource disclosure: `janus://theses`, `janus://forecasts`, `janus://calibration` return full store contents | Leak of hypotheses and forecasts to any caller | Resources are read-only and reuse the same read paths (`server.py:186-229`) | partial | No scoping or redaction per caller |
| Denial of service / resource exhaustion: list tools and `janus_as_of_query` have optional or no limits, and a scenario file is loaded whole | Local process memory or CPU exhaustion | None; the design is single-user and local | not implemented | A malformed or huge input can stall the host process |
| Untrusted tool output is fed to a reasoning model: observation text, theses and review notes are attacker-influenced data | Prompt injection against the assisting model | Software computes indicators, features, calibration and settlement deterministically; the model only reasons over returned data (`README.md:436`; `docs/FORECASTING.md:98-102`) | partial | There is no output provenance marker or sanitization at the MCP boundary |
| Error messages can include absolute local paths | Minor information disclosure in logs or chat | None systematic | not implemented | Paths appear in `ValueError` and `KeyError` text returned to the caller |

**Open risks — MCP tools**

- MCP authentication and authorization are unshipped. Do not describe the MCP
  surface as authenticated until JAN-040's auth task lands and is tested.
- The ledger's immutability is an API property, not a storage guarantee. A
  tamper-evident ledger needs a hash chain or signature and is not in scope
  here.
- There is no tool-call audit log, so post-hoc attribution of a write is
  impossible.

## Surface: local data at rest

The store is a SQLite database under `$JANUS_HOME` (default `~/.janus`,
`config.py:46-60`). Settings and optional provider keys live in
`config.toml` or the environment (`config.py:18-26,155-200`). HTTP responses
and raw source documents may be cached on disk by `data/cache.py` and
`data/blob.py`.

| Threat | Impact | Mitigation | Status | Residual risk |
| --- | --- | --- | --- | --- |
| Provider API keys stored in plaintext in `config.toml` or the environment | Key theft, quota abuse, terms-of-service breach | Environment variables are preferred; `Settings` keeps keys out of `repr` and `redacted()` masks them in CLI output (`config.py:38-50,62-73`, `cli.py:101`) | partial | No keychain or encryption; file permissions depend on the OS umask |
| The SQLite store is readable and writable by any process running as the user | Disclosure of research history; silent tampering with observations, forecasts and reviews | None; the database is a plain SQLite file | not implemented | Copies and backups inherit the same exposure |
| Licensed market data cached on disk can be copied or redistributed | Terms-of-service breach | Documented policy: respect each provider's terms and do not redistribute licensed data (`SECURITY.md`); the repository ignores `*.db`, `/data/` and `*.parquet` (`.gitignore`) | partial | The cache has no provenance or expiry metadata and nothing enforces the policy |
| Secrets committed to the repository | Credential leak in public history | `gitleaks` runs on every push to `main` and every pull request as a blocking job (`.github/workflows/security.yml:15-25`); `.env`, `*.pem` and `*.key` are ignored (`.gitignore`) | implemented | Pattern-based scanning misses novel secret formats; files copied outside the repository are not scanned |
| Environment variables (`JANUS_HOME`, `JANUS_CONFIG`, `JANUS_DB`) redirect reads and writes | An actor able to set the environment chooses which store the process opens | None; this is the local CLI configuration contract | not implemented | Accepted for a single-user local tool: the same actor already runs the process |

**Open risks — local data at rest**

- There is no encryption at rest and no integrity check on the store. A
  resolved Python inventory and any tamper evidence both require a lockfile or
  a signature, which is a separate decision.
- Cache and blob files are raw provider payloads; their retention and deletion
  policy is manual.
- The threat model does not cover the operating system, disk encryption, or
  backups; those are the workflow owner's responsibility.

## Surface: sharing and approvals

`core/janus/share/` implements an approval-first baseline. A share request is
created as `pending`, carries its `as_of` and snapshot hash, and returns an
`ApprovalCard`. Approval signs a canonical envelope with HMAC-SHA256, records
an append-only `share_audit` row, and stores the envelope. Verification checks
the signature, payload hash, key id, and format. The CLI exposes
`janus share request|approve|reject|list|verify`; the secret comes from
`JANUS_SHARE_SECRET` and is never stored in the repository.

| Threat | Impact | Mitigation | Status | Residual risk |
| --- | --- | --- | --- | --- |
| A shared bundle is modified in transit or at rest | The recipient reasons over forged history | Canonical payload hash plus HMAC-SHA256 signature checked by `ShareSigner.verify` | implemented | Symmetric HMAC is only as strong as secret distribution |
| Sender or recipient identity is spoofed | A recipient trusts a bundle from the wrong party | Envelope carries `identity.key_id`; verifier requires the expected key id | partial | No asymmetric key or published identity binding |
| An old, previously valid bundle is replayed | Stale or withdrawn forecasts are presented as current | None; envelopes carry `as_of` but no nonce, expiry, or sequence number | not implemented | A captured envelope remains valid until the key rotates |
| An approval is bypassed by writing the store directly | A change that should need sign-off is applied anyway | The CLI/API path requires a pending request and explicit approval; the audit trail records the decision | partial | Direct SQLite writes are still possible for the same OS user |
| Sharing leaks licensed data or provider keys | Terms-of-service breach or credential leak | `ShareService` refuses empty snapshot hashes; callers choose the payload | not implemented | There is no automatic provider-field/secret filter yet |

**Open risks — sharing and approvals**

- The HMAC signer is a local baseline, not a cross-party identity system. Do not
  describe a verified envelope as proof of a remote human identity.
- Replay protection, expiry, and revocation are not implemented.
- The audit trail is local and append-only by convention; it is not a
  tamper-evident ledger.
- Any future asymmetric signer must keep the same envelope fields and update
  this document in the same change.
