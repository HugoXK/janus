from __future__ import annotations

from typing import Any, Optional

TOOLS = [
    "janus.version",
    "janus.as_of_query",
    "janus.ingest",
    "janus.dashboard.market",
    "janus.dashboard.sector",
    "janus.dashboard.stock",
    "janus.forecast.create",
    "janus.forecast.list",
    "janus.thesis.create",
    "janus.thesis.update",
    "janus.thesis.list",
    "janus.review.debrief",
    "janus.calibrate",
    "janus.persona.list",
    "janus.persona.switch",
    "janus.persona.simulate",
    "janus.backtest.run",
    "janus.beliefbench.run",
]


def build_server(store: Optional[Any] = None) -> Any:
    """Build the MCP server.

    The MCP dependency is optional (``uv sync --extra mcp``). Keeping the import
    lazy means the core library and CLI work without it.
    """

    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError(
            "MCP support is optional. Install it with: uv sync --extra mcp"
        ) from exc

    server = FastMCP("janus")

    @server.tool()
    def janus_version() -> str:
        from janus import __version__

        return __version__

    @server.tool()
    def janus_list_tools() -> list[str]:
        return TOOLS

    # The remaining tools are wired to the store in week 2. The names are
    # intentionally stable so the DSH plugin can be built against them now.
    return server


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
