from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Optional

from ..eval.baselines import ConstantBaseline, RandomBaseline
from ..eval.beliefbench import BeliefBench
from ..forecast.calibration_service import CalibrationService
from ..forecast.ledger import PredictionLedger
from ..forecast.settlement import DirectionOutcomeResolver, SettlementService
from ..memory.models import ObservationKind
from ..memory.store import JanusStore
from ..review.debrief import debrief_prediction
from ..thesis.tracker import ThesisTracker


def _parse_time(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        stamp = value
    else:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.tzinfo.utcoffset(stamp) is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp


def _dump(model: Any) -> dict[str, Any]:
    return model.model_dump(mode="json")


class JanusService:
    """The transport-independent surface behind MCP and the CLI."""

    def __init__(self, store: JanusStore) -> None:
        self.store = store

    def as_of_query(
        self,
        entity_id: str,
        as_of: str | datetime,
        *,
        mode: str = "published",
        kind: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        observation_kind = ObservationKind(kind) if kind else None
        rows = self.store.query_observations_as_of(
            entity_id,
            _parse_time(as_of),
            kind=observation_kind,
            mode=mode,
            limit=limit,
            offset=offset,
        )
        return [_dump(row) for row in rows]

    def create_thesis(
        self,
        *,
        entity_id: str,
        statement: str,
        horizon: str,
        as_of: str | datetime,
        persona_id: Optional[str] = None,
        assumptions: Optional[list[str]] = None,
        catalysts: Optional[list[str]] = None,
        risks: Optional[list[str]] = None,
        falsifiers: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        thesis = ThesisTracker(self.store).create(
            entity_id=entity_id,
            statement=statement,
            horizon=horizon,
            as_of=_parse_time(as_of),
            persona_id=persona_id,
            assumptions=assumptions,
            catalysts=catalysts,
            risks=risks,
            falsifiers=falsifiers,
        )
        return _dump(thesis)

    def list_theses(self) -> list[dict[str, Any]]:
        return [_dump(thesis) for thesis in self.store.list_theses()]

    def create_forecast(
        self,
        *,
        thesis_id: str,
        target: str,
        horizon: str,
        as_of: str | datetime,
        probability: float,
        model_version: str,
        features_hash: str,
        quantiles: Optional[dict[str, float]] = None,
    ) -> dict[str, Any]:
        prediction = PredictionLedger(self.store).record(
            thesis_id=thesis_id,
            target=target,
            horizon=horizon,
            as_of=_parse_time(as_of),
            model_version=model_version,
            features_hash=features_hash,
            probability=probability,
            quantiles=quantiles,
        )
        return _dump(prediction)

    def list_forecasts(
        self, thesis_id: Optional[str] = None
    ) -> list[dict[str, Any]]:
        return [
            _dump(prediction)
            for prediction in self.store.list_predictions(thesis_id=thesis_id)
        ]

    def settle_forecast(
        self,
        *,
        prediction_id: str,
        start_price: float,
        end_price: float,
        realized_at: str | datetime,
        source: str = "mcp",
    ) -> dict[str, Any]:
        outcome = SettlementService(self.store).settle(
            prediction_id,
            DirectionOutcomeResolver(),
            start_price=start_price,
            end_price=end_price,
            source=source,
            realized_at=_parse_time(realized_at),
        )
        return _dump(outcome)

    def debrief(
        self,
        *,
        prediction_id: str,
        features: dict[str, float],
        regime: Optional[str] = None,
        calibration: Optional[float] = None,
        lessons: str = "",
    ) -> dict[str, Any]:
        review = debrief_prediction(
            self.store,
            prediction_id=prediction_id,
            features=features,
            regime=regime,
            calibration=calibration,
            lessons=lessons,
        )
        return _dump(review)

    def calibrate(self) -> dict[str, Any]:
        return asdict(CalibrationService.from_store(self.store))

    def list_personas(self) -> list[dict[str, Any]]:
        return [_dump(persona) for persona in self.store.list_personas()]

    def beliefbench(
        self, scenarios_path: str, baseline: str = "always_up"
    ) -> dict[str, Any]:
        bench = BeliefBench.load(scenarios_path)
        if baseline == "always_up":
            runner = ConstantBaseline(1.0)
        elif baseline == "always_down":
            runner = ConstantBaseline(0.0)
        elif baseline == "random":
            runner = RandomBaseline()
        else:
            raise ValueError("baseline must be always_up, always_down, or random")
        return asdict(bench.run(runner))

    def dump_json(self, payload: Any) -> str:
        return json.dumps(payload, indent=2, sort_keys=True, default=str)
