from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np


@dataclass(frozen=True)
class QuantileForecast:
    quantiles: dict[str, float]
    level: float
    observations: int

    @property
    def width(self) -> float:
        keys = sorted(self.quantiles, key=float)
        if len(keys) < 2:
            return 0.0
        return self.quantiles[keys[-1]] - self.quantiles[keys[0]]


class EmpiricalQuantileModel:
    """Distribution-free return quantiles from point-in-time history.

    The model assumes returns are independent enough that a horizon scales with
    ``sqrt(horizon)``. It is deliberately simple: a documented baseline with an
    explicit sample and no normality assumption.
    """

    def __init__(self, quantiles: Sequence[float] = (0.1, 0.5, 0.9)) -> None:
        values = tuple(float(value) for value in quantiles)
        if not values or any(not 0.0 < value < 1.0 for value in values):
            raise ValueError("quantiles must be strictly between 0 and 1")
        if list(values) != sorted(values):
            raise ValueError("quantiles must be sorted")
        self.quantiles = values
        self.returns_: np.ndarray | None = None

    def fit(self, returns: Iterable[float]) -> "EmpiricalQuantileModel":
        values = np.asarray(list(returns), dtype=float)
        values = values[np.isfinite(values)]
        if values.size < 2:
            raise ValueError("at least two finite returns are required")
        self.returns_ = np.sort(values)
        return self

    def predict(self, *, horizon: int = 1) -> QuantileForecast:
        if self.returns_ is None:
            raise RuntimeError("model is not fitted")
        if horizon < 1:
            raise ValueError("horizon must be >= 1")
        scaled = self.returns_ * float(np.sqrt(horizon))
        values = np.quantile(scaled, self.quantiles)
        mapping = {
            f"{probability:.2f}": float(value)
            for probability, value in zip(self.quantiles, values)
        }
        level = float(self.quantiles[-1] - self.quantiles[0])
        return QuantileForecast(
            quantiles=mapping,
            level=level,
            observations=int(self.returns_.size),
        )

    def coverage(
        self, outcomes: Iterable[float], *, horizon: int = 1
    ) -> float:
        forecast = self.predict(horizon=horizon)
        keys = sorted(forecast.quantiles, key=float)
        low = forecast.quantiles[keys[0]]
        high = forecast.quantiles[keys[-1]]
        values = np.asarray(list(outcomes), dtype=float)
        values = values[np.isfinite(values)]
        if values.size == 0:
            raise ValueError("at least one outcome is required")
        return float(np.mean((values >= low) & (values <= high)))
