from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np


def _sigmoid(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, -50.0, 50.0)
    return 1.0 / (1.0 + np.exp(-clipped))


@dataclass(frozen=True)
class ModelCard:
    name: str
    version: str
    features: tuple[str, ...]
    training_samples: int
    limitations: str


class LogisticDirectionModel:
    """A small, dependency-free logistic baseline.

    Features are standardized before fitting so the RSI scale does not dominate
    the learning rate. This is a baseline, not a trading strategy.
    """

    features = ("rsi_14", "trend", "breadth")

    def __init__(
        self,
        *,
        l2: float = 0.01,
        learning_rate: float = 0.1,
        epochs: int = 500,
    ) -> None:
        self.l2 = l2
        self.learning_rate = learning_rate
        self.epochs = epochs
        self.coef_: np.ndarray | None = None
        self.mean_: np.ndarray | None = None
        self.std_: np.ndarray | None = None
        self.card: ModelCard | None = None

    def fit(
        self,
        features: Sequence[Sequence[float]],
        outcomes: Sequence[float],
    ) -> ModelCard:
        matrix = np.asarray(features, dtype=float)
        labels = np.asarray(outcomes, dtype=float)
        if matrix.ndim != 2 or matrix.shape[1] != len(self.features):
            raise ValueError(f"expected N x {len(self.features)} features")
        if len(matrix) != len(labels):
            raise ValueError("features and outcomes must have the same length")
        if len(matrix) == 0:
            raise ValueError("at least one training row is required")

        self.mean_ = matrix.mean(axis=0)
        self.std_ = matrix.std(axis=0)
        self.std_[self.std_ == 0.0] = 1.0
        normalized = (matrix - self.mean_) / self.std_
        design = np.column_stack([np.ones(len(normalized)), normalized])
        coef = np.zeros(design.shape[1])

        for _ in range(self.epochs):
            predictions = _sigmoid(design @ coef)
            gradient = design.T @ (predictions - labels) / len(labels)
            gradient[1:] += self.l2 * coef[1:]
            coef -= self.learning_rate * gradient

        self.coef_ = coef
        self.card = ModelCard(
            name="logistic-direction",
            version="logit-v1",
            features=self.features,
            training_samples=len(matrix),
            limitations="linear baseline; no transaction costs; not a trading signal",
        )
        return self.card

    def predict_proba(self, features: Sequence[Sequence[float]]) -> np.ndarray:
        if self.coef_ is None or self.mean_ is None or self.std_ is None:
            raise RuntimeError("model is not fitted")
        matrix = np.asarray(features, dtype=float)
        if matrix.ndim == 1:
            matrix = matrix.reshape(1, -1)
        if matrix.ndim != 2 or matrix.shape[1] != len(self.features):
            raise ValueError(f"expected N x {len(self.features)} features")
        normalized = (matrix - self.mean_) / self.std_
        design = np.column_stack([np.ones(len(normalized)), normalized])
        return _sigmoid(design @ self.coef_)

    def predict_one(
        self, *, rsi_value: float, trend: float, breadth: float
    ) -> float:
        return float(self.predict_proba([[rsi_value, trend, breadth]])[0])

    def to_dict(self) -> dict[str, Any]:
        if self.coef_ is None or self.mean_ is None or self.std_ is None or self.card is None:
            raise RuntimeError("model is not fitted")
        return {
            "coef": self.coef_.tolist(),
            "mean": self.mean_.tolist(),
            "std": self.std_.tolist(),
            "l2": self.l2,
            "learning_rate": self.learning_rate,
            "epochs": self.epochs,
            "card": {
                "name": self.card.name,
                "version": self.card.version,
                "features": list(self.card.features),
                "training_samples": self.card.training_samples,
                "limitations": self.card.limitations,
            },
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "LogisticDirectionModel":
        model = cls()
        model.coef_ = np.asarray(payload["coef"], dtype=float)
        model.mean_ = np.asarray(payload["mean"], dtype=float)
        model.std_ = np.asarray(payload["std"], dtype=float)
        model.l2 = float(payload.get("l2", 0.01))
        model.learning_rate = float(payload.get("learning_rate", 0.1))
        model.epochs = int(payload.get("epochs", 500))
        card = payload["card"]
        model.card = ModelCard(
            name=card["name"],
            version=card["version"],
            features=tuple(card["features"]),
            training_samples=int(card["training_samples"]),
            limitations=card["limitations"],
        )
        return model
