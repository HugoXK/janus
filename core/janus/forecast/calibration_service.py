from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence

import numpy as np

from .calibration import (
    brier_score,
    expected_calibration_error,
    log_loss as log_loss_score,
    reliability_curve,
)


def _sigmoid(value: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(value, -50.0, 50.0)))


def _logit(probability: np.ndarray) -> np.ndarray:
    clipped = np.clip(probability, 1e-6, 1.0 - 1e-6)
    return np.log(clipped / (1.0 - clipped))


class PlattCalibrator:
    version = "platt-v1"

    def __init__(self) -> None:
        self.a = 1.0
        self.b = 0.0
        self.fitted = False

    def fit(self, probabilities: Sequence[float], outcomes: Sequence[float]) -> "PlattCalibrator":
        p = np.asarray(probabilities, dtype=float)
        y = np.asarray(outcomes, dtype=float)
        if p.size == 0 or p.shape != y.shape:
            raise ValueError("probabilities and outcomes must be non-empty and aligned")
        z = _logit(p)
        a, b = 1.0, 0.0
        for _ in range(1000):
            predictions = _sigmoid(a * z + b)
            grad_a = float(np.mean((predictions - y) * z))
            grad_b = float(np.mean(predictions - y))
            a -= 0.1 * grad_a
            b -= 0.1 * grad_b
        self.a, self.b, self.fitted = a, b, True
        return self

    def transform(self, probability: float) -> float:
        if not self.fitted:
            return float(probability)
        z = float(_logit(np.asarray([probability]))[0])
        return float(_sigmoid(np.asarray([self.a * z + self.b]))[0])

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "a": self.a, "b": self.b, "fitted": self.fitted}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PlattCalibrator":
        calibrator = cls()
        calibrator.a = float(payload["a"])
        calibrator.b = float(payload["b"])
        calibrator.fitted = bool(payload["fitted"])
        return calibrator


class IsotonicCalibrator:
    version = "isotonic-v1"

    def __init__(self) -> None:
        self.x_: list[float] = []
        self.y_: list[float] = []
        self.fitted = False

    def fit(self, probabilities: Sequence[float], outcomes: Sequence[float]) -> "IsotonicCalibrator":
        p = np.asarray(probabilities, dtype=float)
        y = np.asarray(outcomes, dtype=float)
        if p.size == 0 or p.shape != y.shape:
            raise ValueError("probabilities and outcomes must be non-empty and aligned")
        order = np.argsort(p)
        xs = p[order]
        ys = y[order]
        blocks: list[list[float]] = []
        for x, value in zip(xs, ys):
            blocks.append([float(value), 1.0, float(x), float(x)])
            while len(blocks) >= 2:
                previous, current = blocks[-2], blocks[-1]
                if previous[0] / previous[1] <= current[0] / current[1]:
                    break
                blocks[-2:] = [
                    [
                        previous[0] + current[0],
                        previous[1] + current[1],
                        previous[2],
                        current[3],
                    ]
                ]
        self.x_ = [block[2] for block in blocks]
        self.y_ = [block[0] / block[1] for block in blocks]
        self.fitted = True
        return self

    def transform(self, probability: float) -> float:
        if not self.fitted or not self.x_:
            return float(probability)
        return float(np.interp(float(probability), self.x_, self.y_))

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "x": self.x_,
            "y": self.y_,
            "fitted": self.fitted,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "IsotonicCalibrator":
        calibrator = cls()
        calibrator.x_ = [float(value) for value in payload["x"]]
        calibrator.y_ = [float(value) for value in payload["y"]]
        calibrator.fitted = bool(payload["fitted"])
        return calibrator


@dataclass(frozen=True)
class CalibrationReport:
    n: int
    brier: Optional[float]
    log_loss: Optional[float]
    ece: Optional[float]
    reliability: list[dict[str, float | int | None]]
    by_regime: dict[str, dict[str, float]]
    by_horizon: dict[str, dict[str, float]]
    by_persona: dict[str, dict[str, float]]


class CalibrationService:
    """Fit calibrators and report calibration by slice."""

    def fit(
        self,
        probabilities: Sequence[float],
        outcomes: Sequence[float],
        *,
        method: str = "platt",
    ) -> PlattCalibrator | IsotonicCalibrator:
        if method == "platt":
            return PlattCalibrator().fit(probabilities, outcomes)
        if method == "isotonic":
            return IsotonicCalibrator().fit(probabilities, outcomes)
        raise ValueError("method must be 'platt' or 'isotonic'")

    def report(
        self,
        probabilities: Sequence[float],
        outcomes: Sequence[float],
        metadata: Optional[Sequence[dict[str, Any]]] = None,
    ) -> CalibrationReport:
        p = list(probabilities)
        y = list(outcomes)
        if not p:
            return CalibrationReport(
                n=0,
                brier=None,
                log_loss=None,
                ece=None,
                reliability=[],
                by_regime={},
                by_horizon={},
                by_persona={},
            )
        meta = list(metadata or [{} for _ in p])
        if len(meta) != len(p):
            raise ValueError("metadata must align with probabilities")
        return CalibrationReport(
            n=len(p),
            brier=brier_score(p, y),
            log_loss=log_loss_score(p, y),
            ece=expected_calibration_error(p, y),
            reliability=reliability_curve(p, y),
            by_regime=self._group(meta, p, y, "regime"),
            by_horizon=self._group(meta, p, y, "horizon"),
            by_persona=self._group(meta, p, y, "persona"),
        )

    @classmethod
    def from_store(
        cls,
        store: Any,
        *,
        regime_resolver: Optional[Callable[[Any], Optional[str]]] = None,
    ) -> CalibrationReport:
        probabilities: list[float] = []
        outcomes: list[float] = []
        metadata: list[dict[str, Any]] = []
        for prediction, outcome in store.settled_predictions():
            if prediction.probability is None or outcome.score is None:
                continue
            probabilities.append(float(prediction.probability))
            outcomes.append(float(outcome.score))
            thesis = store.get_thesis(prediction.thesis_id)
            persona = thesis.persona_id if thesis is not None else None
            regime = regime_resolver(prediction) if regime_resolver is not None else None
            metadata.append(
                {
                    "horizon": prediction.horizon,
                    "target": prediction.target,
                    "persona": persona,
                    "regime": regime,
                }
            )
        return cls().report(probabilities, outcomes, metadata)

    @staticmethod
    def _group(
        metadata: Sequence[dict[str, Any]],
        probabilities: Sequence[float],
        outcomes: Sequence[float],
        key: str,
    ) -> dict[str, dict[str, float]]:
        buckets: dict[str, list[tuple[float, float]]] = {}
        for meta, probability, outcome in zip(metadata, probabilities, outcomes):
            value = meta.get(key)
            if value is None:
                continue
            buckets.setdefault(str(value), []).append((probability, outcome))
        report: dict[str, dict[str, float]] = {}
        for name, values in buckets.items():
            p = [value[0] for value in values]
            y = [value[1] for value in values]
            report[name] = {
                "n": float(len(values)),
                "brier": brier_score(p, y),
                "ece": expected_calibration_error(p, y),
            }
        return report
