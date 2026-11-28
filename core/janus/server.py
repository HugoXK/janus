from __future__ import annotations

import hmac
import json
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from . import __version__
from .api_schema import openapi_document
from .config import load_settings
from .contracts import SCHEMA_VERSION
from .mcp.service import JanusService
from .memory.store import JanusStore, open_store

PANEL_HINTS = {
    "market": "materialize market features and build the market dashboard",
    "sector": "materialize sector features and build the sector dashboard",
    "stock": "materialize stock features and build the stock dashboard",
}


def _as_of(params: dict[str, str]) -> str:
    return params.get("as_of") or datetime.now(timezone.utc).isoformat()


def _not_materialized(panel: str, **extra: Any) -> dict[str, Any]:
    return {
        "status": "not_materialized",
        "panel": panel,
        "hint": PANEL_HINTS[panel],
        **extra,
    }


def _fixture(panel: str) -> dict[str, Any]:
    """Return contract-shaped sample payloads for UI development."""

    from .analysis.dashboards import (
        build_market_dashboard,
        build_sector_dashboard,
        build_stock_dashboard,
    )

    as_of = datetime(2026, 1, 2, tzinfo=timezone.utc)
    dashboard: Any
    if panel == "market":
        dashboard = build_market_dashboard(
            as_of=as_of,
            regime="risk-on",
            breadth={"percent_above_ma": 0.62, "mcclellan": 12.4},
            volatility={"percentile": 0.41, "vix": 16.8},
            indices={"SPX": 6025.0, "NDX": 21480.0},
            features_hash="fixture-market",
        )
    elif panel == "sector":
        import pandas as pd

        sectors = pd.DataFrame(
            {
                "relative_return_63d": [0.081, -0.024],
                "rs_ratio": [104.2, 96.1],
                "rs_momentum": [101.8, 98.9],
                "quadrant": ["leading", "lagging"],
                "breadth": [0.68, 0.34],
            },
            index=["Technology", "Energy"],
        )
        dashboard = build_sector_dashboard(
            as_of=as_of,
            benchmark="SPX",
            sectors=sectors,
            features_hash="fixture-sector",
        )
    else:
        dashboard = build_stock_dashboard(
            as_of=as_of,
            entity_id="AAPL",
            close=232.5,
            features={"rsi_14": 58.2, "return_21d": 0.043, "feature_version": "v1"},
            features_hash="fixture-stock",
        )
    return dashboard.model_dump(mode="json")


class _Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started = time.monotonic()
        self.requests = 0
        self.errors = 0
        self.by_path: dict[str, int] = {}

    def record(self, path: str) -> None:
        with self._lock:
            self.requests += 1
            self.by_path[path] = self.by_path.get(path, 0) + 1

    def record_error(self) -> None:
        with self._lock:
            self.errors += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "requests": self.requests,
                "errors": self.errors,
                "by_path": dict(sorted(self.by_path.items())),
                "uptime_seconds": round(time.monotonic() - self._started, 3),
            }


class JanusHandler(BaseHTTPRequestHandler):
    service: JanusService
    token: Optional[str] = None
    metrics: _Metrics = _Metrics()
    request_id: str = ""

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def _authorized(self) -> bool:
        if self.token is None:
            return True
        supplied = self.headers.get("Authorization", "")
        expected = f"Bearer {self.token}"
        return hmac.compare_digest(supplied, expected)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        params = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
        self.request_id = self.headers.get("X-Request-ID") or uuid4().hex
        self.metrics.record(parsed.path)
        try:
            if parsed.path == "/openapi.json":
                self._json(200, openapi_document())
                return
            if parsed.path == "/metrics":
                self._json(200, self.metrics.snapshot())
                return
            if parsed.path == "/health":
                self._json(
                    200,
                    {
                        "status": "ok",
                        "version": __version__,
                        "schema_version": SCHEMA_VERSION,
                    },
                )
                return
            if not self._authorized():
                self._json(401, {"error": "unauthorized"})
                return
            if parsed.path == "/api/panels":
                self._json(
                    200,
                    [
                        {"id": panel, "hint": hint}
                        for panel, hint in PANEL_HINTS.items()
                    ],
                )
                return
            if parsed.path.startswith("/api/panels/"):
                panel = parsed.path.rsplit("/", 1)[-1]
                if panel not in PANEL_HINTS:
                    self._json(
                        404, {"error": "not_found", "path": parsed.path}
                    )
                    return
                if params.get("fixture") in {"1", "true", "yes"}:
                    self._json(200, _fixture(panel))
                    return
                if panel != "stock":
                    self._json(200, _not_materialized(panel))
                    return
                entity_id = params.get("entity_id", "")
                if not entity_id:
                    raise ValueError("entity_id is required for the stock panel")
                dashboard = self.service.stock_dashboard(
                    entity_id, _as_of(params)
                )
                if dashboard is None:
                    self._json(
                        200, _not_materialized(panel, entity_id=entity_id)
                    )
                else:
                    self._json(200, dashboard)
                return
            if parsed.path == "/api/as_of":
                entity_id = params.get("entity_id", "")
                limit = int(params["limit"]) if params.get("limit") else None
                offset = int(params.get("offset", "0"))
                rows = self.service.as_of_query(
                    entity_id,
                    _as_of(params),
                    mode=params.get("mode", "published"),
                    kind=params.get("kind"),
                    limit=limit,
                    offset=offset,
                )
                self._json(200, rows)
                return
            if parsed.path == "/api/theses":
                self._json(200, self.service.list_theses())
                return
            if parsed.path == "/api/forecasts":
                self._json(200, self.service.list_forecasts(params.get("thesis_id")))
                return
            if parsed.path == "/api/calibrate":
                self._json(200, self.service.calibrate())
                return
            if parsed.path == "/api/brief":
                self._json(
                    200,
                    self.service.brief(
                        params.get("entity_id", ""),
                        params.get("as_of"),
                        limit=10,
                    ),
                )
                return
            if parsed.path == "/api/snapshot":
                entity_id = params.get("entity_id", "")
                if not entity_id:
                    raise ValueError("entity_id is required for a snapshot")
                self._json(
                    200, self.service.snapshot(entity_id, _as_of(params))
                )
                return
            self._json(404, {"error": "not_found", "path": parsed.path})
        except Exception as exc:  # noqa: BLE001 - local HTTP boundary
            self.metrics.record_error()
            self._json(400, {"error": type(exc).__name__, "message": str(exc)})

    def _json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        if self.request_id:
            self.send_header("X-Request-ID", self.request_id)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return


def make_server(
    store: Optional[JanusStore] = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8766,
    token: Optional[str] = None,
) -> ThreadingHTTPServer:
    service = JanusService(store or open_store(load_settings().database))
    handler = type(
        "BoundJanusHandler",
        (JanusHandler,),
        {"service": service, "token": token, "metrics": _Metrics()},
    )
    return ThreadingHTTPServer((host, port), handler)


def serve(
    store: Optional[JanusStore] = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8766,
    token: Optional[str] = None,
) -> None:
    server = make_server(store, host=host, port=port, token=token)
    try:
        server.serve_forever()
    finally:
        server.server_close()
