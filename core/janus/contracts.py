"""Domain contract metadata and JSON Schema export.

The Pydantic models are the source of truth. This module gives the models a
version and a serialized shape that other tools can validate against.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .memory.models import Observation, Outcome, Persona, Prediction, Review, Thesis

SCHEMA_VERSION = 2

CONTRACT_MODELS = {
    "Observation": Observation,
    "Thesis": Thesis,
    "Prediction": Prediction,
    "Outcome": Outcome,
    "Persona": Persona,
    "Review": Review,
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
