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
| `janus_provenance_trace` | Resolve an observation to its citation and raw source |
| `janus_scenario_tree` | Generate an up/base/down tree with falsifiers |
| `janus_quantile_forecast` | Empirical 10/50/90 return quantiles |

## Resources

| URI | Payload |
| --- | --- |
| `janus://theses` | All theses |
| `janus://forecasts` | All forecasts |
| `janus://calibration` | Calibration report |
| `janus://provenance` | Citation catalog for known observations |
| `janus://market` | Market dashboard placeholder (`not_materialized`) |
| `janus://sector` | Sector dashboard placeholder (`not_materialized`) |
| `janus://stock` | Stock dashboard placeholder (`not_materialized`) |

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
