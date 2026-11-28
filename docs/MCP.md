# MCP surface

Janus exposes its core as an MCP server. The Python service is transport
independent (`core/janus/mcp/service.py`); the FastMCP wrapper is in
`core/janus/mcp/server.py`.

```bash
uv sync --extra dev --extra mcp
uv run python -m janus.mcp.server
```

The `mcp` extra supports MCP 1.x and 2.x. The server uses `FastMCP` on 1.x and
`MCPServer` on 2.x; CI exercises both.

The default store is the configured SQLite database. Tests inject
`JanusStore(":memory:")` through `build_server(store)`.

## Tools

| Tool | Purpose |
| --- | --- |
| `janus_as_of_query` | Read observations that were knowable at an as-of time |
| `janus_thesis_create` | Create a thesis with falsifiers |
| `janus_thesis_list` | List theses |
| `janus_forecast_create` | Record a forecast before the outcome |
| `janus_forecast_list` | List forecasts |
| `janus_forecast_settle` | Resolve a P(up) forecast against prices |
| `janus_review_debrief` | Attribution, calibration, and lessons |
| `janus_calibrate` | Calibration report over settled predictions |
| `janus_persona_list` | List stored personas and weights |
| `janus_beliefbench_run` | Run a baseline over a scenario file |
| `janus_corporate_actions` | List corporate actions, bounded by security and as-of |
| `janus_adjust_price` | Split-adjusted price with an explicit basis |
| `janus_source_spans` | Source spans attached to one observation |
| `janus_source_citation` | Citation with span, locator, and excerpt |
| `janus_mcp_approval_list` | List write approvals, as of a point in time (admin scope) |
| `janus_mcp_approval_decide` | Approve or deny a pending write (admin scope) |
| `janus_scenario_tree` | Generate an up/base/down tree with falsifiers |
| `janus_quantile_forecast` | Empirical 10/50/90 return quantiles |
| `janus_quality` | Duplicate/provenance/price/staleness checks for one as-of view |

## Resources

| URI | Payload |
| --- | --- |
| `janus://theses` | All theses |
| `janus://forecasts` | All forecasts |
| `janus://calibration` | Calibration report |
| `janus://market` | Market dashboard placeholder (`not_materialized`) |
| `janus://sector` | Sector dashboard placeholder (`not_materialized`) |
| `janus://stock` | Stock dashboard placeholder (`not_materialized`) |

## Scoped auth and write approvals

The MCP server runs with per-caller tokens and scope checks on every tool and
resource. The implementation is `core/janus/mcp/auth.py`; enforcement lives in
`core/janus/mcp/service.py`, so calling the service directly (bypassing the
FastMCP wrapper) is denied exactly the same way.

**Scopes.** `read` covers observation queries, theses/forecasts/personas
listings, calibration, security and universe lookups, and BeliefBench runs.
`write` covers `janus_thesis_create`, `janus_forecast_create`,
`janus_forecast_settle`, and `janus_review_debrief`. `admin` covers listing and
deciding approvals. Scopes do not imply each other: a caller needs `read`
explicitly and `write` explicitly. A tool or resource with no declared scope is
denied (fail closed), and a test enumerates the registrations and fails when a
declaration is missing.

**Configuration (environment).**

| Variable | Meaning |
| --- | --- |
| `JANUS_MCP_TOKENS` | JSON registry: `{"callers": [{"id": "...", "token": "..." , "scopes": ["read"], "expires_at": "..."}]}`. `token_sha256` may replace `token`. |
| `JANUS_MCP_TOKEN` | Raw token the server process presents (one caller per stdio process). |
| `JANUS_MCP_WRITE_APPROVALS` | `1`/`true`/`yes`/`on` enables the approval path. Writes are disabled otherwise. |
| `JANUS_MCP_APPROVAL_TTL_SECONDS` | Approval lifetime; default `900`. |

Tokens are hashed with SHA-256 on load and never appear in errors, audit rows,
or tool responses. A missing or bad token fails closed with `token_invalid`; an
expired caller token fails with `token_expired`.

**Approval flow.** The first call to a write tool records a pending approval
(caller, tool, canonical argument hash, `created_at`, `expires_at`) and returns
a typed `approval_required` error with the approval id. An `admin` caller
approves it with `janus mcp approve <id>` (or the `janus_mcp_approval_decide`
tool). The identical call then executes exactly once; a replay returns
`approval_consumed`, changed arguments create a new approval, and a denied or
expired approval returns `approval_denied` / `approval_expired`. No write
happens until the approval is granted.

**Least-privilege example.** Give the research agent a caller token with
`["read", "write"]` and keep the `admin` token out of that process; approve
writes from a separate shell:

```bash
export JANUS_MCP_TOKENS='{"callers":[
  {"id":"agent","token":"agent-token","scopes":["read","write"]},
  {"id":"operator","token":"operator-token","scopes":["read","admin"]}]}'
export JANUS_MCP_WRITE_APPROVALS=1

# agent process: write attempt -> approval_required (no data written)
JANUS_MCP_TOKEN=agent-token uv run python -m janus.mcp.server

# operator shell:
JANUS_MCP_TOKEN=operator-token uv run janus mcp approve apv-...
JANUS_MCP_TOKEN=operator-token uv run janus mcp audit --as-of 2026-01-02T03:04:05Z
```

**Audit.** Denials, approval decisions, executions, and failed executions append
to `mcp_audit` (time, caller, tool, decision, code, argument hash, approval id;
no secrets). SQLite triggers reject `UPDATE` and `DELETE`, so the trail is
append-only. `janus mcp audit` and `janus mcp approvals` accept `--as-of` for
point-in-time queries and return rows in `(recorded_at, seq)` order.

**Not included.** OAuth/OIDC, multi-tenant identity, transport encryption,
remote listeners, an approval notification UI, and a general policy engine. The
transport remains local stdio/trusted, so a process that can set the server's
environment can choose its own token; this is documented as residual risk in
`docs/SECURITY-THREAT-MODEL.md`.

## HTTP panel API

`janus serve` exposes the same service over a local JSON API used by the DSH
plugin. It is read-only:

| Route | Payload |
| --- | --- |
| `GET /health` | Version and schema version |
| `GET /openapi.json` | OpenAPI 3.1 contract for the local API |
| `GET /metrics` | Request counters, error count, per-path counts, uptime |
| `GET /api/as_of` | Observations knowable at `as_of` |
| `GET /api/theses` | Theses and falsifiers |
| `GET /api/forecasts` | Forecast ledger |
| `GET /api/calibrate` | Calibration report |
| `GET /api/brief` | Brief for one entity |
| `GET /api/snapshot` | Hash-addressed as-of observation snapshot |
| `GET /api/panels` | Available panels |
| `GET /api/panels/market` | MarketDashboard or `not_materialized` |
| `GET /api/panels/sector` | SectorDashboard or `not_materialized` |
| `GET /api/panels/stock` | StockDashboard or `not_materialized` |

When `JANUS_API_TOKEN` is set for `janus serve`, every `/api/*` route requires
`Authorization: Bearer <token>`; `/health` remains open for readiness checks.

Panel routes accept `fixture=1` for contract-shaped sample data. The stock route
requires `entity_id` and reads the latest feature materialization at or before
`as_of`; market and sector routes return an explicit `not_materialized` payload
with a hint until those features exist.

## Notes

- The server is read/write only through explicit tools; resources are read-only.
- `janus_forecast_settle` expects target `direction` or `up`; the probability is
  P(up).
- The MCP dependency is optional; the core library and CLI do not need it.
- `janus_beliefbench_run` is restricted to the server's `scenarios_root`
  (default: the working directory).
- The DSH plugin is a thin shell over this surface; it does not reimplement
  memory or calibration.
