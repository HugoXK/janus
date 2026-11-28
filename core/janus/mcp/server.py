from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any, Callable, Optional

from ..config import load_settings
from ..memory.store import JanusStore
from .auth import AuthorizationError, Authorizer, authorizer_from_env
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
    "janus_counterfactual_replay",
    "janus_persona_tournament",
    "janus_mcp_approval_list",
    "janus_mcp_approval_decide",
    "janus_scenario_tree",
    "janus_quantile_forecast",
]

RESOURCES = [
    "janus://theses",
    "janus://forecasts",
    "janus://calibration",
    "janus://market",
    "janus://sector",
    "janus://stock",
]


def _guarded(function: Callable[..., Any]) -> Callable[..., Any]:
    """Turn a typed authorization failure into a stable error payload."""

    @functools.wraps(function)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return function(*args, **kwargs)
        except AuthorizationError as exc:
            return {"error": exc.to_dict()}

    return wrapper


def _guarded_json(function: Callable[..., str]) -> Callable[..., str]:
    @functools.wraps(function)
    def wrapper(*args: Any, **kwargs: Any) -> str:
        try:
            return function(*args, **kwargs)
        except AuthorizationError as exc:
            return json.dumps({"error": exc.to_dict()}, sort_keys=True)

    return wrapper


def build_server(
    store: Optional[JanusStore] = None,
    scenarios_root: Optional[Path] = None,
    authorizer: Optional[Authorizer] = None,
) -> Any:
    """Build the MCP server.

    The MCP dependency is optional (``uv sync --extra mcp``). Keeping the import
    lazy means the core library and CLI work without it.
    """

    server_class = _server_class()

    janus_store = store or JanusStore(load_settings().database)
    service = JanusService(
        janus_store,
        scenarios_root=scenarios_root or Path.cwd(),
        authorizer=authorizer or authorizer_from_env(janus_store),
    )
    server = server_class("janus")

    @server.tool()
    @_guarded
    def janus_version() -> Any:
        """Return the Janus version."""
        from janus import __version__

        service.require_read("janus_version")
        return __version__

    @server.tool()
    @_guarded
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
    @_guarded
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
    @_guarded
    def janus_thesis_list() -> list[dict[str, Any]]:
        """List theses."""
        return service.list_theses()

    @server.tool()
    @_guarded
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
    @_guarded
    def janus_forecast_list(thesis_id: Optional[str] = None) -> list[dict[str, Any]]:
        """List forecasts, optionally for one thesis."""
        return service.list_forecasts(thesis_id=thesis_id)

    @server.tool()
    @_guarded
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
    @_guarded
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
    @_guarded
    def janus_calibrate() -> dict[str, Any]:
        """Calibration report over settled predictions."""
        return service.calibrate()

    @server.tool()
    @_guarded
    def janus_persona_list() -> list[dict[str, Any]]:
        """List stored personas and their weights."""
        return service.list_personas()

    @server.tool()
    @_guarded
    def janus_beliefbench_run(
        scenarios_path: str, baseline: str = "always_up"
    ) -> dict[str, Any]:
        """Run a baseline over a BeliefBench scenario file."""
        return service.beliefbench(scenarios_path, baseline)

    @server.tool()
    @_guarded
    def janus_counterfactual_replay(
        prediction_id: str,
        remove_evidence: Optional[list[str]] = None,
        persona_id: Optional[str] = None,
        feature_overrides: Optional[dict[str, float]] = None,
    ) -> dict[str, Any]:
        """Replay a decision with swapped evidence or persona."""
        return service.counterfactual_replay(
            prediction_id=prediction_id,
            remove_evidence=remove_evidence,
            persona_id=persona_id,
            feature_overrides=feature_overrides,
        )

    @server.tool()
    @_guarded
    def janus_persona_tournament(
        scenarios_path: str,
        seed: int = 7,
        bootstrap: int = 1000,
        confidence: float = 0.95,
    ) -> dict[str, Any]:
        """Compare all stored personas on one fixed scenario set."""
        return service.persona_tournament(
            scenarios_path,
            seed=seed,
            bootstrap=bootstrap,
            confidence=confidence,
        )

    @server.tool()
    @_guarded
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
    @_guarded
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
    @_guarded
    def janus_universe_members(universe: str, as_of: str) -> list[dict[str, Any]]:
        """Return the point-in-time members of a universe."""
        return service.universe_members(universe, as_of)

    @server.tool()
    @_guarded
    def janus_corporate_actions(
        security_id: Optional[str] = None, as_of: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """List corporate actions, optionally bounded by security and as-of."""
        return service.corporate_actions(security_id, as_of)

    @server.tool()
    @_guarded
    def janus_adjust_price(
        security_id: str, raw_price: float, as_of: str
    ) -> dict[str, Any]:
        """Return a split-adjusted price with an explicit adjustment basis."""
        return service.adjust_price(security_id, raw_price, as_of)

    @server.tool()
    @_guarded
    def janus_source_spans(observation_id: str) -> list[dict[str, Any]]:
        """List exact source spans attached to one observation."""
        return service.source_spans(observation_id)

    @server.tool()
    @_guarded
    def janus_source_citation(
        observation_id: str, span_id: Optional[str] = None
    ) -> dict[str, Any]:
        """Return a citation with the source span, locator, and excerpt."""
        return service.source_citation(observation_id, span_id)

    @server.tool()
    @_guarded
    def janus_mcp_approval_list(as_of: Optional[str] = None) -> Any:
        """List write approvals, optionally as of a point in time (admin scope)."""
        return service.list_approvals(as_of)

    @server.tool()
    @_guarded
    def janus_mcp_approval_decide(approval_id: str, decision: str) -> Any:
        """Approve or deny a pending write approval (admin scope)."""
        return service.decide_approval(approval_id, decision)

    @server.resource("janus://theses")
    @_guarded_json
    def theses_resource() -> str:
        service.require_resource("janus://theses")
        return json.dumps(service.list_theses(), default=str)

    @server.resource("janus://forecasts")
    @_guarded_json
    def forecasts_resource() -> str:
        service.require_resource("janus://forecasts")
        return json.dumps(service.list_forecasts(), default=str)

    @server.resource("janus://calibration")
    @_guarded_json
    def calibration_resource() -> str:
        service.require_resource("janus://calibration")
        return json.dumps(service.calibrate(), default=str)

    @server.resource("janus://market")
    @_guarded_json
    def market_resource() -> str:
        service.require_resource("janus://market")
        return json.dumps(
            {
                "status": "not_materialized",
                "panel": "market",
                "hint": "materialize features and build the market dashboard",
            }
        )

    @server.resource("janus://sector")
    @_guarded_json
    def sector_resource() -> str:
        service.require_resource("janus://sector")
        return json.dumps(
            {
                "status": "not_materialized",
                "panel": "sector",
                "hint": "materialize sector features and build the sector dashboard",
            }
        )

    @server.resource("janus://stock")
    @_guarded_json
    def stock_resource() -> str:
        service.require_resource("janus://stock")
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
