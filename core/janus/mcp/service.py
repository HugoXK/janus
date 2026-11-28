from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from ..analysis.dashboards import build_stock_dashboard
from ..analysis.feature_store import FeatureStore
from ..eval.baselines import ConstantBaseline, RandomBaseline
from ..eval.beliefbench import BeliefBench, Scenario, ScenarioResult
from ..forecast.calibration_service import CalibrationService
from ..forecast.ledger import PredictionLedger
from ..forecast.settlement import DirectionOutcomeResolver, SettlementService
from ..memory.models import ObservationKind
from ..memory.store import JanusStore
from ..review.debrief import debrief_prediction
from ..thesis.tracker import ThesisTracker
from .auth import AuthorizationError, Authorizer


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
    """The transport-independent surface behind MCP and the CLI.

    ``authorizer`` is optional for backwards compatibility with the trusted
    local CLI, but the MCP server always supplies one. When it is present,
    every tool and resource checks its declared scope here, so calling the
    service directly cannot bypass the FastMCP wrapper.
    """

    def __init__(
        self,
        store: JanusStore,
        scenarios_root: Optional[Path] = None,
        authorizer: Optional[Authorizer] = None,
    ) -> None:
        self.store = store
        self.scenarios_root = scenarios_root
        self.authorizer = authorizer

    # ------------------------------------------------------------------
    # Scoped access
    # ------------------------------------------------------------------
    def require_read(self, tool: str) -> None:
        if self.authorizer is not None:
            self.authorizer.require_read(tool)

    def require_resource(self, uri: str) -> None:
        if self.authorizer is not None:
            self.authorizer.require_resource(uri)

    def _write(
        self, tool: str, arguments: dict[str, Any], action: Callable[[], Any]
    ) -> Any:
        if self.authorizer is None:
            return action()
        return self.authorizer.authorize_write(tool, arguments, action)

    def list_approvals(self, as_of: str | datetime | None = None) -> list[dict[str, Any]]:
        if self.authorizer is None:
            raise AuthorizationError(
                "scope_denied", "approvals require a scoped authorizer"
            )
        stamp = _parse_time(as_of) if as_of is not None else None
        return self.authorizer.list_approvals(stamp)

    def decide_approval(self, approval_id: str, decision: str) -> dict[str, Any]:
        if self.authorizer is None:
            raise AuthorizationError(
                "scope_denied", "approvals require a scoped authorizer"
            )
        return self.authorizer.decide(approval_id, decision)

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
        self.require_read("janus_as_of_query")
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
        arguments: dict[str, Any] = {
            "entity_id": entity_id,
            "statement": statement,
            "horizon": horizon,
            "as_of": as_of,
            "persona_id": persona_id,
            "assumptions": assumptions,
            "catalysts": catalysts,
            "risks": risks,
            "falsifiers": falsifiers,
        }
        return self._write(
            "janus_thesis_create",
            arguments,
            lambda: self._create_thesis(**arguments),
        )

    def _create_thesis(
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
        self.require_read("janus_thesis_list")
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
        arguments: dict[str, Any] = {
            "thesis_id": thesis_id,
            "target": target,
            "horizon": horizon,
            "as_of": as_of,
            "probability": probability,
            "model_version": model_version,
            "features_hash": features_hash,
            "quantiles": quantiles,
        }
        return self._write(
            "janus_forecast_create",
            arguments,
            lambda: self._create_forecast(**arguments),
        )

    def _create_forecast(
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
        self.require_read("janus_forecast_list")
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
        arguments: dict[str, Any] = {
            "prediction_id": prediction_id,
            "start_price": start_price,
            "end_price": end_price,
            "realized_at": realized_at,
            "source": source,
        }
        return self._write(
            "janus_forecast_settle",
            arguments,
            lambda: self._settle_forecast(**arguments),
        )

    def _settle_forecast(
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
        arguments: dict[str, Any] = {
            "prediction_id": prediction_id,
            "features": features,
            "regime": regime,
            "calibration": calibration,
            "lessons": lessons,
        }
        return self._write(
            "janus_review_debrief",
            arguments,
            lambda: self._debrief(**arguments),
        )

    def _debrief(
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
        self.require_read("janus_calibrate")
        return asdict(CalibrationService.from_store(self.store))

    def security_resolve(
        self, symbol: str, as_of: str | datetime, *, exchange: Optional[str] = None
    ) -> dict[str, Any]:
        self.require_read("janus_security_resolve")
        from ..memory.security_master import SecurityMaster

        security = SecurityMaster(self.store).resolve(
            symbol, _parse_time(as_of), exchange=exchange
        )
        if security is None:
            raise KeyError(f"security not found: {symbol}")
        return security.to_dict()

    def security_history(self, symbol: str) -> list[dict[str, Any]]:
        from ..memory.security_master import SecurityMaster

        return [item.to_dict() for item in SecurityMaster(self.store).history(symbol)]

    def universe_members(
        self, universe: str, as_of: str | datetime
    ) -> list[dict[str, Any]]:
        self.require_read("janus_universe_members")
        from ..memory.security_master import SecurityMaster

        return [
            item.to_dict()
            for item in SecurityMaster(self.store).members(
                universe, _parse_time(as_of)
            )
        ]

    def corporate_actions(
        self, security_id: Optional[str] = None, as_of: Optional[str | datetime] = None
    ) -> list[dict[str, Any]]:
        self.require_read("janus_corporate_actions")
        from ..memory.corporate_actions import CorporateActionLedger

        stamp = _parse_time(as_of) if as_of is not None else None
        return [
            action.to_dict()
            for action in CorporateActionLedger(self.store).list(
                security_id, as_of=stamp
            )
        ]

    def adjust_price(
        self, security_id: str, raw_price: float, as_of: str | datetime
    ) -> dict[str, Any]:
        self.require_read("janus_adjust_price")
        from ..memory.corporate_actions import CorporateActionLedger

        return CorporateActionLedger(self.store).adjust_price(
            security_id, raw_price, _parse_time(as_of)
        )

    def source_spans(self, observation_id: str) -> list[dict[str, Any]]:
        self.require_read("janus_source_spans")
        from ..memory.spans import SpanStore

        return [span.to_dict() for span in SpanStore(self.store).list(observation_id)]

    def source_citation(
        self, observation_id: str, span_id: Optional[str] = None
    ) -> dict[str, Any]:
        self.require_read("janus_source_citation")
        from ..memory.spans import SpanStore

        return SpanStore(self.store).citation(
            observation_id, span_id=span_id
        ).to_dict()

    def list_personas(self) -> list[dict[str, Any]]:
        self.require_read("janus_persona_list")
        return [_dump(persona) for persona in self.store.list_personas()]

    def persona_tournament(
        self,
        scenarios_path: str,
        *,
        seed: int = 7,
        bootstrap: int = 1000,
        confidence: float = 0.95,
    ) -> dict[str, Any]:
        from ..persona.tournament import PersonaTournament

        if self.scenarios_root is None:
            raise ValueError("scenario path is unavailable: no scenarios root configured")
        path = Path(scenarios_path).resolve()
        root = self.scenarios_root.resolve()
        if path != root and root not in path.parents:
            raise ValueError("scenario path is outside the configured root")
        if not 1 <= bootstrap <= 10000:
            raise ValueError("bootstrap must be between 1 and 10000")
        tournament = PersonaTournament.load(path)
        report = tournament.run(
            self.store.list_personas(),
            seed=seed,
            bootstrap=bootstrap,
            confidence=confidence,
        )
        payload = report.to_dict()
        json.dumps(payload, allow_nan=False)
        return payload

    def counterfactual_replay(
        self,
        *,
        prediction_id: str,
        remove_evidence: Optional[list[str]] = None,
        persona_id: Optional[str] = None,
        feature_overrides: Optional[dict[str, float]] = None,
    ) -> dict[str, Any]:
        from ..review.counterfactual import CounterfactualReplay

        report = CounterfactualReplay(self.store).replay(
            prediction_id,
            remove_evidence=remove_evidence or [],
            persona_id=persona_id,
            feature_overrides=feature_overrides,
        )
        return report.to_dict()

    def scenario_tree(
        self,
        *,
        entity_id: str,
        horizon: str,
        as_of: str | datetime,
        direction_probability: float,
        volatility: float = 0.02,
        trend: float = 0.0,
        evidence: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        from ..forecast.scenarios import generate_scenario_tree

        tree = generate_scenario_tree(
            entity_id=entity_id,
            horizon=horizon,
            as_of=_parse_time(as_of),
            direction_probability=direction_probability,
            volatility=volatility,
            trend=trend,
            evidence=evidence,
        )
        return _dump(tree)

    def quantile_forecast(
        self, returns: list[float], *, horizon: int = 1
    ) -> dict[str, Any]:
        from ..forecast.quantiles import EmpiricalQuantileModel

        forecast = EmpiricalQuantileModel().fit(returns).predict(horizon=horizon)
        return {**asdict(forecast), "width": forecast.width}
    def brief(
        self,
        entity_id: str,
        as_of: str | datetime | None = None,
        *,
        limit: int = 10,
    ) -> dict[str, Any]:
        stamp = _parse_time(as_of) if as_of is not None else datetime.now(timezone.utc)
        observations = (
            self.as_of_query(entity_id, stamp, limit=limit) if entity_id else []
        )
        return {
            "as_of": stamp.isoformat(),
            "entity_id": entity_id,
            "calibration": self.calibrate(),
            "theses": self.list_theses(),
            "forecasts": self.list_forecasts(),
            "observations": observations,
            "sector": {"status": "not_materialized"},
        }

    def snapshot(
        self, entity_id: str, as_of: str | datetime
    ) -> dict[str, Any]:
        stamp = _parse_time(as_of)
        observations = self.as_of_query(entity_id, stamp)
        payload = {
            "entity_id": entity_id,
            "as_of": stamp.isoformat(),
            "observations": observations,
        }
        canonical = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), default=str
        )
        return {
            **payload,
            "count": len(observations),
            "snapshot_hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        }

    def stock_dashboard(
        self, entity_id: str, as_of: str | datetime
    ) -> Optional[dict[str, Any]]:
        """Build the stock panel from the latest feature materialization.

        Returns ``None`` when no features exist at or before ``as_of``; the
        transport layer turns that into an explicit ``not_materialized``
        payload rather than a zeroed dashboard.
        """

        snapshot = FeatureStore(self.store).snapshot(entity_id, _parse_time(as_of))
        if snapshot is None:
            return None
        features = snapshot["features"]
        dashboard = build_stock_dashboard(
            as_of=datetime.fromisoformat(snapshot["as_of"]),
            entity_id=entity_id,
            close=float(features.get("close", 0.0)),
            features=features,
            features_hash=snapshot["features_hash"],
        )
        return _dump(dashboard)

    def beliefbench(
        self, scenarios_path: str, baseline: str = "always_up"
    ) -> dict[str, Any]:
        self.require_read("janus_beliefbench_run")
        path = Path(scenarios_path).resolve()
        if self.scenarios_root is not None:
            root = self.scenarios_root.resolve()
            if path != root and root not in path.parents:
                raise ValueError("scenario path is outside the configured root")
        bench = BeliefBench.load(path)
        runner: Callable[[Scenario], ScenarioResult]
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
