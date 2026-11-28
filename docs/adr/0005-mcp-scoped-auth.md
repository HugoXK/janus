# ADR 0005: Scope-checked MCP tools with explicit write approvals

## Status

Proposed. Implemented in #151 (JAN-143); Dev Lead sign-off is requested in the
pull request before this is marked Accepted.

## Context

The MCP server was local stdio with no authentication: any process that could
speak to the transport could call every tool, including the four write tools.
The store is the research record, so an unauthenticated write boundary makes
attribution and calibration evidence impossible to defend. The threat model
listed "any local process can call every MCP tool" as `not implemented` and
noted there was no tool-call audit log.

The repository is single-user and local-first. A hosted identity system
(OAuth/OIDC, SSO, multi-tenant) is out of scope; the problem is the process and
client boundary, and the fact that approval for writes currently exists only as
process convention.

## Decision

1. **Scopes on registrations.** Every MCP tool and resource declares exactly one
   of `read`, `write`, `admin` in `core/janus/mcp/auth.py`. A name without a
   declaration is denied at runtime; a test enumerates the server's registered
   functions and fails when a declaration is missing.
2. **Per-caller tokens.** `JANUS_MCP_TOKENS` maps token digests to caller ids,
   scopes, and optional expiry; `JANUS_MCP_TOKEN` is the token the server
   process presents. Tokens are SHA-256 hashed on load, compared with
   `hmac.compare_digest`, and never written to errors, audit rows, or responses.
   A missing/unknown/expired token fails closed.
3. **Enforcement in the service layer.** `JanusService` receives an optional
   `Authorizer`; when present, every tool checks its declared scope there.
   Calling the service directly cannot bypass the FastMCP wrapper.
4. **Writes are approval-first and disabled by default.** With
   `JANUS_MCP_WRITE_APPROVALS` unset, a write is denied with `write_disabled`.
   When enabled, the first call creates an approval bound to caller, tool,
   canonical argument hash (order-independent, `None`-normalized), `created_at`,
   and `expires_at`, and returns `approval_required` without touching the store.
   An `admin` caller approves or denies through `janus mcp approve|deny` or the
   admin tools. Execution is claimed atomically, so replay of the same arguments
   gets `approval_consumed`, changed arguments need a new approval, and a
   denied/expired approval returns `approval_denied`/`approval_expired`.
5. **Append-only audit.** Denials, decisions, executions, and failed executions
   append to `mcp_audit` (time, caller, tool, decision, code, argument hash,
   approval id; no secrets). SQLite triggers reject `UPDATE` and `DELETE`.
   Queries are ordered by `(recorded_at, seq)` and accept `as_of`.
6. **Storage.** Approvals and audit reuse the existing SQLite store (migration
   v7) so as-of queries and backup follow the rest of the data.

## Consequences

- The default MCP server now denies everything until a token registry is
  configured. This is a deliberate fail-closed break; `docs/MCP.md` documents
  the least-privilege setup.
- The CLI (`janus brief`, `janus mcp audit`, …) still runs as a trusted local
  user without an authorizer; the same OS user can read the database directly.
  The control is about the tool boundary, not OS isolation.
- `write` does not imply `admin` and vice versa. A single caller with both can
  self-approve; the documented deployment keeps `admin` out of the agent
  process.
- Audit rows are not hash-chained or signed (JAN-148 is the tamper-evident
  ledger). Reopen this decision if a hash chain is required, if a hosted or
  remote transport is added, or if approvals need to bind to a human identity
  rather than a local token.
