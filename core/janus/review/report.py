from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from ..data.quality import QualityReport, check_observations
from ..forecast.calibration_service import CalibrationService
from ..memory.models import Observation
from ..memory.store import JanusStore

DISCLAIMER = "Janus is research tooling, not investment advice. It does not execute trades."


def _snapshot_hash(observations: list[Observation]) -> str:
    payload = [
        {
            "id": observation.id,
            "published_at": observation.published_at.isoformat(),
            "raw_hash": observation.raw_hash,
            "value": observation.value,
        }
        for observation in sorted(observations, key=lambda item: item.id)
    ]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _sanitize(value: Any) -> Any:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, dict):
        return {key: _sanitize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def _citation(observation: Observation) -> str:
    where = observation.raw_uri or observation.raw_hash
    return f"{observation.source} {observation.published_at.isoformat()} {where}"


def _cell(value: Any) -> str:
    """Escape one Markdown table cell."""

    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def _inline(value: Any) -> str:
    """Keep free text on one Markdown line."""

    return str(value).replace("\r", " ").replace("\n", " ")


@dataclass(frozen=True)
class ResearchReport:
    entity_id: str
    as_of: str
    snapshot_hash: str
    evidence: list[dict[str, Any]]
    theses: list[dict[str, Any]]
    forecasts: list[dict[str, Any]]
    calibration: dict[str, Any]
    quality: dict[str, Any]
    disclaimer: str = DISCLAIMER

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_markdown(self) -> str:
        lines = [
            f"# Janus research report — {self.entity_id}",
            "",
            f"- as-of: `{self.as_of}`",
            f"- snapshot: `{self.snapshot_hash}`",
            f"- evidence rows: {len(self.evidence)}",
            f"- theses: {len(self.theses)}",
            f"- forecasts: {len(self.forecasts)}",
            "",
            "## Evidence",
            "",
        ]
        if self.evidence:
            lines.extend(["| id | source | published | citation |", "| --- | --- | --- | --- |"])
            for item in self.evidence:
                lines.append(
                    f"| `{_cell(item['id'])}` | {_cell(item['source'])} | "
                    f"{_cell(item['published_at'])} | {_cell(item['citation'])} |"
                )
        else:
            lines.append("No evidence visible at this as-of time.")
        lines.extend(["", "## Theses", ""])
        if self.theses:
            for thesis in self.theses:
                falsifiers = "; ".join(thesis.get("falsifiers", [])) or "none recorded"
                lines.append(
                    f"- **{_inline(thesis['id'])}** "
                    f"({_inline(thesis['horizon'])}, {_inline(thesis['status'])}): "
                    f"{_inline(thesis['statement'])}  \n  falsifiers: {_inline(falsifiers)}"
                )
        else:
            lines.append("No theses recorded.")
        lines.extend(["", "## Forecasts", ""])
        if self.forecasts:
            for forecast in self.forecasts:
                lines.append(
                    f"- `{forecast['id']}` target={forecast['target']} "
                    f"p={forecast.get('probability')} horizon={forecast['horizon']} "
                    f"outcome={forecast.get('outcome_id') or 'open'}"
                )
        else:
            lines.append("No forecasts recorded.")
        lines.extend(
            [
                "",
                "## Calibration",
                "",
                "- scope: store-wide (all entities, all times)",
                f"- settled: {self.calibration.get('n')}",
                f"- Brier: {self.calibration.get('brier')}",
                f"- ECE: {self.calibration.get('ece')}",
                f"- log loss: {self.calibration.get('log_loss')}",
                "",
                "## Data quality",
                "",
            ]
        )
        if self.quality["errors"] or self.quality["warnings"]:
            for label in ("errors", "warnings"):
                for issue in self.quality[label]:
                    lines.append(f"- {label[:-1]}: `{issue['code']}` {issue['message']}")
        else:
            lines.append("No quality issues.")
        lines.extend(["", "---", "", self.disclaimer, ""])
        return "\n".join(lines).rstrip() + "\n"


def _quality_payload(report: QualityReport) -> dict[str, Any]:
    return {
        "checked": report.checked,
        "errors": [asdict(issue) for issue in report.errors],
        "warnings": [asdict(issue) for issue in report.warnings],
    }


def build_research_report(
    store: JanusStore,
    entity_id: str,
    as_of: datetime,
    *,
    limit: int = 50,
) -> ResearchReport:
    """Build a deterministic report from only the as-of view."""

    if as_of.tzinfo is None or as_of.tzinfo.utcoffset(as_of) is None:
        raise ValueError("as_of must be timezone-aware")
    observations = store.query_observations_as_of(
        entity_id, as_of, mode="published", limit=limit
    )
    theses = [
        thesis.model_dump(mode="json")
        for thesis in store.list_theses()
        if thesis.entity_id == entity_id and thesis.as_of <= as_of
    ]
    thesis_ids = {thesis["id"] for thesis in theses}
    forecasts = [
        forecast.model_dump(mode="json")
        for forecast in store.list_predictions()
        if forecast.thesis_id in thesis_ids and forecast.as_of <= as_of
    ]
    calibration = _sanitize(asdict(CalibrationService.from_store(store)))
    quality = _quality_payload(check_observations(observations, as_of=as_of))
    evidence = [
        {
            "id": observation.id,
            "source": observation.source,
            "kind": observation.kind.value,
            "published_at": observation.published_at.isoformat(),
            "raw_hash": observation.raw_hash,
            "citation": _citation(observation),
        }
        for observation in sorted(observations, key=lambda item: (item.published_at, item.id))
    ]
    return ResearchReport(
        entity_id=entity_id,
        as_of=as_of.astimezone(timezone.utc).isoformat(),
        snapshot_hash=_snapshot_hash(observations),
        evidence=evidence,
        theses=sorted(theses, key=lambda item: item["id"]),
        forecasts=sorted(forecasts, key=lambda item: item["id"]),
        calibration=calibration,
        quality=quality,
    )
