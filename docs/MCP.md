# MCP surface

Janus exposes its core as an MCP server. The Python service is transport
independent (`core/janus/mcp/service.py`); the FastMCP wrapper is in
`core/janus/mcp/server.py`.

```bash
uv sync --extra dev --extra mcp
uv run python -m janus.mcp.server
```

The `mcp` extra is pinned to `mcp>=1.0,<2` for v0.1.0 because MCP 2.x renamed
`FastMCP` to `MCPServer` and changed the server API. v0.2 will support both.

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

## Resources

| URI | Payload |
| --- | --- |
| `janus://theses` | All theses |
| `janus://forecasts` | All forecasts |
| `janus://calibration` | Calibration report |
| `janus://market` | Market dashboard placeholder (`not_materialized`) |
| `janus://sector` | Sector dashboard placeholder (`not_materialized`) |
| `janus://stock` | Stock dashboard placeholder (`not_materialized`) |

## Notes

- The server is read/write only through explicit tools; resources are read-only.
- `janus_forecast_settle` expects target `direction` or `up`; the probability is
  P(up).
- The MCP dependency is optional; the core library and CLI do not need it.
- `janus_beliefbench_run` is restricted to the server's `scenarios_root`
  (default: the working directory).
- The DSH plugin is a thin shell over this surface; it does not reimplement
  memory or calibration.
