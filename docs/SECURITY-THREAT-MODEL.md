# Security threat model

Janus is local-first research software. It does not execute trades, holds no
broker credentials, and has no network service listening for inbound
connections. This document covers the three surfaces that do exist — the MCP
boundary, local data at rest, and the (unshipped) sharing/approval surface —
and states honestly which controls are live today.

**Status vocabulary.** Every row uses exactly one of:

- `implemented` — the control exists in shipped code and is exercised.
- `partial` — a control exists but does not cover the whole threat.
- `planned` — designed or backlogged, **not** shipped, protects nothing today.
- `not implemented` — no control exists.

`Status` reflects the code at the base this document was written against
(`88ac454`, the `main` this revision was verified against); every citation
below was re-checked against that tree. A planned control is never described as
preventing anything.
If a later change ships the sharing surface (see JAN-043 and
`docs/ARCHITECTURE.md:30`), this document must be updated against that code
before it is merged, not against the branch that adds it.

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
| Ledger tampering: a recorded forecast is meant to be immutable | Ex-post rewriting of predictions would destroy calibration evidence | The API has no update or delete path for a prediction; settlement only attaches an outcome (`core/janus/forecast/ledger.py:11-17`, `core/janus/memory/store.py:360-366`) | partial | No database trigger, hash chain, or signature; direct SQLite edits by the same user are undetectable |
| Resource disclosure: `janus://theses`, `janus://forecasts`, `janus://calibration` return full store contents | Leak of hypotheses and forecasts to any caller | Resources are read-only and reuse the same read paths (`server.py:186-229`) | partial | No scoping or redaction per caller |
| Denial of service / resource exhaustion: list tools and `janus_as_of_query` have optional or no limits, and a scenario file is loaded whole | Local process memory or CPU exhaustion | None; the design is single-user and local | not implemented | A malformed or huge input can stall the host process |
| Untrusted tool output is fed to a reasoning model: observation text, theses and review notes are attacker-influenced data | Prompt injection against the assisting model | Software computes indicators, features, calibration and settlement deterministically; the model only reasons over returned data (`CONTRIBUTING.md`, "Principles" section; `docs/FORECASTING.md`, "LLM role" section) | partial | There is no output provenance marker or sanitization at the MCP boundary |
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

Fitted model artifacts are a second local data location: `ModelRegistry`
(`core/janus/forecast/registry.py`) writes one canonical JSON document per
artifact to `$JANUS_HOME/models` (default `~/.janus/models`), named by the
SHA-256 of its content and written with an atomic replace. A read re-derives
that address, so an edited artifact is rejected as corrupt instead of used
silently; nothing signs the directory, though, so an artifact placed there by
the same OS user cannot be told apart from a locally fitted one
(`docs/DATA_MODEL.md`, "Model artifacts (files)").

| Threat | Impact | Mitigation | Status | Residual risk |
| --- | --- | --- | --- | --- |
| Provider API keys stored in plaintext in `config.toml` or the environment | Key theft, quota abuse, terms-of-service breach | Environment variables are preferred; `Settings` keeps keys out of `repr` and `redacted()` masks them in CLI output (defined in `core/janus/config.py`; surfaced by `janus config show` in `core/janus/cli.py`) | partial | No keychain or encryption; file permissions depend on the OS umask |
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

**This surface does not exist at this base.** There is no `core/janus/share/`
package, no approval object, no signed bundle and no verification code.
`docs/ARCHITECTURE.md:30` says the shell "Reuses FlyBot and bot-social for
scheduling, approvals, and sharing", and `docs/BACKLOG.md` lists JAN-043
"Approvals and signed sharing" as M4/P1 — both are plans, not shipped behaviour. Until that
work lands, the only sharing control is that nothing is shared by Janus.

| Threat | Impact | Mitigation | Status | Residual risk |
| --- | --- | --- | --- | --- |
| A shared bundle is modified in transit or at rest | The recipient reasons over forged history | None; no bundle format or signature exists yet | not implemented | Any future unauthenticated bundle format would be trivially forgeable |
| Sender or recipient identity is spoofed | A recipient trusts a bundle from the wrong party | None; no identity binding exists yet | not implemented | — |
| An old, previously valid bundle is replayed | Stale or withdrawn forecasts are presented as current | None; no nonce, expiry, or sequence number exists yet | not implemented | — |
| An approval is bypassed by writing the store directly | A change that should need sign-off is applied anyway | None; there is no approval flow and no write barrier | not implemented | The approval surface, when built, must not rely on UI-only gating |
| Sharing leaks licensed data or provider keys | Terms-of-service breach or credential leak | None; nothing is shared | planned | Sharing must filter provider payloads and secrets by construction |

**Open risks — sharing and approvals**

- Approvals and signed sharing are **not implemented**. No signature is a live
  control on this base, and no planned sharing feature may be described as one.
- When the surface lands it must ship signature verification, sender/recipient
  identity binding, and replay protection together with tests; any one missing
  leaves the others decorative.
- The MCP boundary and the sharing boundary must not share an implicit trust
  channel: a bundle received from another party is untrusted input.

## Cross-cutting controls

| Control | Where | Status | Note |
| --- | --- | --- | --- |
| Secret scanning | `gitleaks`, `.github/workflows/security.yml:15-25` | implemented | Blocking; runs on push to `main` and on pull requests |
| Dependency audit | `pip-audit`, `.github/workflows/security.yml:27-35` | partial | Advisory only (`continue-on-error: true`); it cannot fail a pull request |
| Component inventory | `scripts/generate_sbom.py`, advisory `sbom` job | partial | CycloneDX 1.5 subset; Python entries are declared constraints, not resolved versions, because there is no lockfile |
| Dependency updates | `.github/dependabot.yml` | implemented | Weekly for pip, npm and GitHub Actions; `open-pull-requests-limit: 5` per ecosystem is a ceiling, not the current count |
| Static analysis / fuzzing | — | not implemented | No SAST, and no fuzzing focused on the security surfaces |
| Reproducible builds | — | not implemented | No lockfile for Python and no build attestation |

The dependency policy behind this table is in `SECURITY.md`.
