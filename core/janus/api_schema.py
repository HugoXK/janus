from __future__ import annotations

from typing import Any


def openapi_document() -> dict[str, Any]:
    """Return the OpenAPI contract for the local read-only JSON API."""

    json_response = {"200": {"description": "JSON payload"}}
    security = [{"bearerAuth": []}]
    paths: dict[str, Any] = {
        "/health": {
            "get": {
                "summary": "Readiness and version",
                "responses": json_response,
            }
        },
        "/api/as_of": {
            "get": {
                "summary": "Observations knowable at an as-of time",
                "security": security,
                "parameters": [
                    {"name": "entity_id", "in": "query", "required": True, "schema": {"type": "string"}},
                    {"name": "as_of", "in": "query", "schema": {"type": "string", "format": "date-time"}},
                    {"name": "mode", "in": "query", "schema": {"enum": ["published", "observed"]}},
                    {"name": "kind", "in": "query", "schema": {"type": "string"}},
                    {"name": "limit", "in": "query", "schema": {"type": "integer"}},
                    {"name": "offset", "in": "query", "schema": {"type": "integer"}},
                ],
                "responses": json_response,
            }
        },
        "/api/theses": {
            "get": {"summary": "Theses", "security": security, "responses": json_response}
        },
        "/api/forecasts": {
            "get": {"summary": "Forecast ledger", "security": security, "responses": json_response}
        },
        "/api/calibrate": {
            "get": {"summary": "Calibration report", "security": security, "responses": json_response}
        },
        "/api/brief": {
            "get": {
                "summary": "Brief for one entity",
                "security": security,
                "parameters": [
                    {"name": "entity_id", "in": "query", "schema": {"type": "string"}},
                    {"name": "as_of", "in": "query", "schema": {"type": "string", "format": "date-time"}},
                ],
                "responses": json_response,
            }
        },
        "/api/snapshot": {
            "get": {
                "summary": "Hash-addressed as-of observation snapshot",
                "security": security,
                "parameters": [
                    {"name": "entity_id", "in": "query", "required": True, "schema": {"type": "string"}},
                    {"name": "as_of", "in": "query", "schema": {"type": "string", "format": "date-time"}},
                ],
                "responses": json_response,
            }
        },
        "/api/panels": {
            "get": {"summary": "Available panels", "security": security, "responses": json_response}
        },
    }
    for panel in ("market", "sector", "stock"):
        parameters = [
            {"name": "fixture", "in": "query", "schema": {"type": "string"}},
        ]
        if panel == "stock":
            parameters.extend(
                [
                    {"name": "entity_id", "in": "query", "required": True, "schema": {"type": "string"}},
                    {"name": "as_of", "in": "query", "schema": {"type": "string", "format": "date-time"}},
                ]
            )
        paths[f"/api/panels/{panel}"] = {
            "get": {
                "summary": f"{panel.title()} panel",
                "security": security,
                "parameters": parameters,
                "responses": json_response,
            }
        }
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Janus local JSON API",
            "version": "0.1.0",
            "description": "Read-only local API for the DSH plugin; research tooling, not advice.",
        },
        "components": {
            "securitySchemes": {
                "bearerAuth": {"type": "http", "scheme": "bearer"}
            }
        },
        "paths": paths,
    }
