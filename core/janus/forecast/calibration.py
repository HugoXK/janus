from __future__ import annotations

from typing import Sequence

import numpy as np


def _as_arrays(
    probabilities: Sequence[float], outcomes: Sequence[float]
) -> tuple[np.ndarray, np.ndarray]:
    p = np.asarray(probabilities, dtype=float)
    y = np.asarray(outcomes, dtype=float)
    if p.shape != y.shape:
        raise ValueError("probabilities and outcomes must have the same shape")
    if p.size == 0:
        raise ValueError("at least one prediction is required")
    if np.any((p < 0.0) | (p > 1.0)):
        raise ValueError("probabilities must be in [0, 1]")
    return p, y


def brier_score(probabilities: Sequence[float], outcomes: Sequence[float]) -> float:
    """Mean squared error between forecast probabilities and binary outcomes."""

    p, y = _as_arrays(probabilities, outcomes)
    return float(np.mean((p - y) ** 2))


def log_loss(
    probabilities: Sequence[float], outcomes: Sequence[float], eps: float = 1e-12
) -> float:
    p, y = _as_arrays(probabilities, outcomes)
    p = np.clip(p, eps, 1.0 - eps)
    return float(-np.mean(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))


def reliability_curve(
    probabilities: Sequence[float], outcomes: Sequence[float], bins: int = 10
) -> list[dict[str, float | int | None]]:
    """Binned calibration data for a reliability diagram.

    Empty bins carry ``None`` rather than NaN so the report is strict JSON.
    """

    p, y = _as_arrays(probabilities, outcomes)
    edges = np.linspace(0.0, 1.0, bins + 1)
    curve: list[dict[str, float | int | None]] = []
    for index in range(bins):
        lower, upper = edges[index], edges[index + 1]
        if index == bins - 1:
            mask = (p >= lower) & (p <= upper)
        else:
            mask = (p >= lower) & (p < upper)
        count = int(mask.sum())
        if count == 0:
            curve.append(
                {
                    "bin_lower": float(lower),
                    "bin_upper": float(upper),
                    "count": 0,
                    "mean_predicted": None,
                    "observed_frequency": None,
                }
            )
            continue
        curve.append(
            {
                "bin_lower": float(lower),
                "bin_upper": float(upper),
                "count": count,
                "mean_predicted": float(p[mask].mean()),
                "observed_frequency": float(y[mask].mean()),
            }
        )
    return curve


def expected_calibration_error(
    probabilities: Sequence[float], outcomes: Sequence[float], bins: int = 10
) -> float:
    p, y = _as_arrays(probabilities, outcomes)
    curve = reliability_curve(p.tolist(), y.tolist(), bins=bins)
    total = len(p)
    ece = 0.0
    for bucket in curve:
        count = bucket["count"]
        mean = bucket["mean_predicted"]
        observed = bucket["observed_frequency"]
        if not isinstance(count, int) or count == 0:
            continue
        if not isinstance(mean, (int, float)) or not isinstance(observed, (int, float)):
            continue
        ece += (count / total) * abs(float(mean) - float(observed))
    return float(ece)
