"""Domain contract metadata and JSON Schema export.

The Pydantic models are the source of truth. This module gives the models a
version and a serialized shape that other tools can validate against.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .analysis.dashboards import (
    MarketDashboard,
    SectorDashboard,
    SectorRow,
    StockDashboard,
)
from .memory.models import Observation, Outcome, Persona, Prediction, Review, Thesis

SCHEMA_VERSION = 5

CONTRACT_MODELS: dict[str, type[BaseModel]] = {
    "Observation": Observation,
    "Thesis": Thesis,
    "Prediction": Prediction,
    "Outcome": Outcome,
    "Persona": Persona,
    "Review": Review,
    "MarketDashboard": MarketDashboard,
    "SectorRow": SectorRow,
    "SectorDashboard": SectorDashboard,
    "StockDashboard": StockDashboard,
}


def export_schema() -> dict[str, Any]:
    """Return the full contract schema as a JSON-serializable dict."""

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Janus domain contracts",
        "schema_version": SCHEMA_VERSION,
        "$defs": {
            name: model.model_json_schema()
            for name, model in CONTRACT_MODELS.items()
        },
    }


def write_schema(path: str | Path) -> Path:
    """Write the contract schema with stable formatting."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(export_schema(), indent=2, sort_keys=True) + "\n")
    return target


def load_schema(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def check_schema(path: str | Path) -> tuple[bool, str]:
    """Check the contract, not the renderer's formatting.

    Pydantic's JSON Schema output changes between minor versions. The checked-in
    file is valid when the model set, the schema version, and the required
    fields match the models.
    """

    try:
        schema = load_schema(path)
    except FileNotFoundError:
        return False, f"missing schema: {path}"
    except json.JSONDecodeError as exc:
        return False, f"invalid JSON in {path}: {exc}"

    if schema.get("schema_version") != SCHEMA_VERSION:
        return (
            False,
            f"schema_version {schema.get('schema_version')!r} != {SCHEMA_VERSION}",
        )

    definitions = schema.get("$defs", {})
    if set(definitions) != set(CONTRACT_MODELS):
        return (
            False,
            f"models {sorted(definitions)} != {sorted(CONTRACT_MODELS)}",
        )

    for name, model in CONTRACT_MODELS.items():
        expected = {
            field for field, info in model.model_fields.items() if info.is_required()
        }
        actual = set(definitions.get(name, {}).get("required", []))
        if actual != expected:
            return (
                False,
                f"{name} required fields differ: {sorted(actual ^ expected)}",
            )
    return True, f"schema ok: {path}"
