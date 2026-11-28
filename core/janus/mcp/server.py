from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from ..config import load_settings
from ..memory.store import JanusStore
from .service import JanusService

def _server_class() -> Any:
    try:
        from mcp.server.fastmcp import FastMCP

        return FastMCP
    except ImportError:
        try:
            from mcp.server.mcpserver import MCPServer
        except ImportError as exc:  # pragma: no cover - optional extra
            raise RuntimeError(
                "MCP support is optional. Install it with: uv sync --extra mcp"
            ) from exc
        return MCPServer


TOOLS = [
    "janus_version",
    "janus_as_of_query",
    "janus_thesis_create",
    "janus_thesis_list",
    "janus_forecast_create",
    "janus_forecast_list",
    "janus_forecast_settle",
    "janus_review_debrief",
    "janus_calibrate",
    "janus_security_resolve",
    "janus_universe_members",
    "janus_corporate_actions",
    "janus_adjust_price",
    "janus_source_spans",
    "janus_source_citation",
    "janus_persona_list",
    "janus_beliefbench_run",
    "janus_provenance_trace",
    "janus_scenario_tree",
    "janus_quantile_forecast",
]


def build_server(
    store: Optional[JanusStore] = None,
    scenarios_root: Optional[Path] = None,
) -> Any:
    """Build the MCP server.

    The MCP dependency is optional (``uv sync --extra mcp``). Keeping the import
    lazy means the core library and CLI work without it.
    """

    server_class = _server_class()

    service = JanusService(
        store or JanusStore(load_settings().database),
        scenarios_root=scenarios_root or Path.cwd(),
    )
    server = server_class("janus")

    @server.tool()
    def janus_version() -> str:
        """Return the Janus version."""
        from janus import __version__

        return __version__

    @server.tool()
    def janus_as_of_query(
        entity_id: str,
        as_of: str,
        mode: str = "published",
        kind: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return observations that were knowable at ``as_of``."""
        return service.as_of_query(
            entity_id,
            as_of,
            mode=mode,
            kind=kind,
            limit=limit,
            offset=offset,
        )

    @server.tool()
    def janus_thesis_create(
        entity_id: str,
        statement: str,
        horizon: str,
        as_of: str,
        persona_id: Optional[str] = None,
        falsifiers: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Create a thesis with explicit falsifiers."""
        return service.create_thesis(
            entity_id=entity_id,
            statement=statement,
            horizon=horizon,
            as_of=as_of,
            persona_id=persona_id,
            falsifiers=falsifiers,
        )

    @server.tool()
    def janus_thesis_list() -> list[dict[str, Any]]:
        """List theses."""
        return service.list_theses()

    @server.tool()
    def janus_forecast_create(
        thesis_id: str,
        target: str,
        horizon: str,
        as_of: str,
        probability: float,
        model_version: str,
        features_hash: str,
    ) -> dict[str, Any]:
        """Record a forecast before the outcome is known."""
        return service.create_forecast(
            thesis_id=thesis_id,
            target=target,
            horizon=horizon,
            as_of=as_of,
            probability=probability,
            model_version=model_version,
            features_hash=features_hash,
        )

    @server.tool()
    def janus_forecast_list(thesis_id: Optional[str] = None) -> list[dict[str, Any]]:
        """List forecasts, optionally for one thesis."""
        return service.list_forecasts(thesis_id=thesis_id)

    @server.tool()
    def janus_forecast_settle(
        prediction_id: str,
        start_price: float,
        end_price: float,
        realized_at: str,
        source: str = "mcp",
    ) -> dict[str, Any]:
        """Settle a P(up) forecast against a start/end price pair."""
        return service.settle_forecast(
            prediction_id=prediction_id,
            start_price=start_price,
            end_price=end_price,
            realized_at=realized_at,
            source=source,
        )

    @server.tool()
    def janus_review_debrief(
        prediction_id: str,
        features: dict[str, float],
        regime: Optional[str] = None,
        calibration: Optional[float] = None,
        lessons: str = "",
    ) -> dict[str, Any]:
        """Attribution, calibration, and lessons for a settled prediction."""
        return service.debrief(
            prediction_id=prediction_id,
            features=features,
            regime=regime,
            calibration=calibration,
            lessons=lessons,
        )

    @server.tool()
    def janus_calibrate() -> dict[str, Any]:
        """Calibration report over settled predictions."""
        return service.calibrate()

    @server.tool()
    def janus_persona_list() -> list[dict[str, Any]]:
        """List stored personas and their weights."""
        return service.list_personas()

    @server.tool()
    def janus_beliefbench_run(
        scenarios_path: str, baseline: str = "always_up"
    ) -> dict[str, Any]:
        """Run a baseline over a BeliefBench scenario file."""
        return service.beliefbench(scenarios_path, baseline)

    @server.tool()
    def janus_provenance_trace(observation_id: str) -> dict[str, Any]:
        """Resolve an observation to its citation and source span."""
        return service.provenance_trace(observation_id)

    @server.resource("janus://provenance")
    def provenance_resource() -> str:
        return json.dumps(service.provenance_catalog(), default=str)

    @server.tool()
    def janus_scenario_tree(
        entity_id: str,
        horizon: str,
        as_of: str,
        direction_probability: float,
        volatility: float = 0.02,
        trend: float = 0.0,
        evidence: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Generate a scenario tree whose probabilities sum to one."""
        return service.scenario_tree(
            entity_id=entity_id,
            horizon=horizon,
            as_of=as_of,
            direction_probability=direction_probability,
            volatility=volatility,
            trend=trend,
            evidence=evidence,
        )

    @server.tool()
    def janus_quantile_forecast(
        returns: list[float], horizon: int = 1
    ) -> dict[str, Any]:
        """Return empirical 10/50/90 return quantiles and interval width."""
        return service.quantile_forecast(returns, horizon=horizon)

    @server.tool()
    def janus_security_resolve(
        symbol: str, as_of: str, exchange: Optional[str] = None
    ) -> dict[str, Any]:
        """Resolve a symbol to its security master row at an as-of time."""
        return service.security_resolve(symbol, as_of, exchange=exchange)

    @server.tool()
    def janus_universe_members(universe: str, as_of: str) -> list[dict[str, Any]]:
        """Return the point-in-time members of a universe."""
        return service.universe_members(universe, as_of)

    @server.tool()
    def janus_corporate_actions(
        security_id: Optional[str] = None, as_of: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """List corporate actions, optionally bounded by security and as-of."""
        return service.corporate_actions(security_id, as_of)

    @server.tool()
    def janus_adjust_price(
        security_id: str, raw_price: float, as_of: str
    ) -> dict[str, Any]:
        """Return a split-adjusted price with an explicit adjustment basis."""
        return service.adjust_price(security_id, raw_price, as_of)

    @server.tool()
    def janus_source_spans(observation_id: str) -> list[dict[str, Any]]:
        """List exact source spans attached to one observation."""
        return service.source_spans(observation_id)

    @server.tool()
    def janus_source_citation(
        observation_id: str, span_id: Optional[str] = None
    ) -> dict[str, Any]:
        """Return a citation with the source span, locator, and excerpt."""
        return service.source_citation(observation_id, span_id)

    @server.resource("janus://theses")
    def theses_resource() -> str:
        return json.dumps(service.list_theses(), default=str)

    @server.resource("janus://forecasts")
    def forecasts_resource() -> str:
        return json.dumps(service.list_forecasts(), default=str)

    @server.resource("janus://calibration")
    def calibration_resource() -> str:
        return json.dumps(service.calibrate(), default=str)

    @server.resource("janus://market")
    def market_resource() -> str:
        return json.dumps(
            {
                "status": "not_materialized",
                "panel": "market",
                "hint": "materialize features and build the market dashboard",
            }
        )

    @server.resource("janus://sector")
    def sector_resource() -> str:
        return json.dumps(
            {
                "status": "not_materialized",
                "panel": "sector",
                "hint": "materialize sector features and build the sector dashboard",
            }
        )

    @server.resource("janus://stock")
    def stock_resource() -> str:
        return json.dumps(
            {
                "status": "not_materialized",
                "panel": "stock",
                "hint": "materialize stock features and build the stock dashboard",
            }
        )

    return server


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
