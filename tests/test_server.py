from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone

import pytest

from janus.analysis.feature_store import FeatureStore
from janus.memory.models import Observation, ObservationKind
from janus.memory.store import JanusStore
from janus.server import make_server


@pytest.fixture()
def base_url():
    store = JanusStore(":memory:")
    as_of = datetime(2026, 1, 2, tzinfo=timezone.utc)
    FeatureStore(store).materialize(
        "ACME",
        as_of,
        {"close": 101.5, "rsi_14": 61.0, "feature_version": "v1"},
    )
    store.insert_observation(
        Observation(
            id="news-1",
            entity_id="ACME",
            kind=ObservationKind.news,
            source="rss",
            published_at=as_of,
            value={"title": "ACME wins"},
            raw_hash="hash-1",
        )
    )
    server = make_server(store, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield url
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _get(url: str, token: str | None = None) -> dict:
    request = urllib.request.Request(url)
    if token is not None:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode())


def test_health(base_url) -> None:
    payload = _get(f"{base_url}/health")
    assert payload["status"] == "ok"
    assert payload["schema_version"] >= 1


def test_as_of_query(base_url) -> None:
    rows = _get(
        f"{base_url}/api/as_of?entity_id=ACME&as_of=2026-01-03T00:00:00%2B00:00"
    )
    assert [row["id"] for row in rows] == ["news-1"]


def test_brief(base_url) -> None:
    payload = _get(f"{base_url}/api/brief?entity_id=ACME")
    assert payload["entity_id"] == "ACME"
    assert payload["observations"][0]["id"] == "news-1"
    assert "calibration" in payload
    assert payload["sector"]["status"] == "not_materialized"


def test_panel_index(base_url) -> None:
    payload = _get(f"{base_url}/api/panels")
    assert {row["id"] for row in payload} == {"market", "sector", "stock"}


def test_market_and_sector_are_explicitly_not_materialized(base_url) -> None:
    market = _get(f"{base_url}/api/panels/market")
    sector = _get(f"{base_url}/api/panels/sector")
    assert market["status"] == "not_materialized"
    assert market["panel"] == "market"
    assert sector["status"] == "not_materialized"
    assert "hint" in sector


def test_panel_fixtures_match_contracts(base_url) -> None:
    market = _get(f"{base_url}/api/panels/market?fixture=1")
    sector = _get(f"{base_url}/api/panels/sector?fixture=1")
    stock = _get(f"{base_url}/api/panels/stock?fixture=1")
    assert market["regime"] == "risk-on"
    assert market["features_hash"] == "fixture-market"
    assert sector["benchmark"] == "SPX"
    assert sector["sectors"][0]["quadrant"] == "leading"
    assert stock["entity_id"] == "AAPL"
    assert stock["features_hash"] == "fixture-stock"


def test_stock_panel_uses_materialized_features(base_url) -> None:
    payload = _get(
        f"{base_url}/api/panels/stock?entity_id=ACME"
        "&as_of=2026-01-03T00:00:00%2B00:00"
    )
    assert payload["entity_id"] == "ACME"
    assert payload["close"] == 101.5
    assert payload["features"]["rsi_14"] == 61.0
    assert payload["as_of"].startswith("2026-01-02")


def test_stock_panel_reports_missing_features(base_url) -> None:
    payload = _get(
        f"{base_url}/api/panels/stock?entity_id=MISSING"
        "&as_of=2026-01-03T00:00:00%2B00:00"
    )
    assert payload["status"] == "not_materialized"
    assert payload["entity_id"] == "MISSING"


def test_stock_panel_requires_entity(base_url) -> None:
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _get(f"{base_url}/api/panels/stock")
    assert excinfo.value.code == 400


def test_unknown_panel_is_404(base_url) -> None:
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _get(f"{base_url}/api/panels/nope")
    assert excinfo.value.code == 404


def test_openapi_contract_lists_panel_routes(base_url) -> None:
    payload = _get(f"{base_url}/openapi.json")
    assert payload["openapi"] == "3.1.0"
    assert "/api/panels/stock" in payload["paths"]
    assert "bearerAuth" in payload["components"]["securitySchemes"]
    assert payload["paths"]["/api/panels/stock"]["get"]["security"] == [
        {"bearerAuth": []}
    ]


def test_token_protects_api_but_not_health() -> None:
    store = JanusStore(":memory:")
    server = make_server(store, port=0, token="secret")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        assert _get(f"{url}/health")["status"] == "ok"
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            _get(f"{url}/api/theses")
        assert excinfo.value.code == 401
        assert _get(f"{url}/api/theses", token="secret") == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_metrics_and_request_id(base_url) -> None:
    request = urllib.request.Request(f"{base_url}/metrics")
    request.add_header("X-Request-ID", "req-123")
    with urllib.request.urlopen(request, timeout=5) as response:
        payload = json.loads(response.read().decode())
        assert response.headers["X-Request-ID"] == "req-123"
    assert payload["requests"] >= 1
    assert payload["by_path"]["/metrics"] >= 1
    assert payload["uptime_seconds"] >= 0
