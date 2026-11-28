from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Callable, Optional, Sequence

import numpy as np

from .calibration import brier_score, log_loss


class LeakDetected(ValueError):
    """Raised when timestamps or fold boundaries would leak the future."""


@dataclass(frozen=True)
class Fold:
    train_start: int
    train_end: int
    test_start: int
    test_end: int


@dataclass(frozen=True)
class FoldResult:
    fold: Fold
    train_samples: int
    test_samples: int
    brier: float
    log_loss: float
    accuracy: float
    gross_return: Optional[float]
    net_return: Optional[float]
    turnover: Optional[float]


@dataclass(frozen=True)
class BacktestReport:
    folds: list[FoldResult]
    brier: float
    log_loss: float
    accuracy: float
    gross_return: Optional[float]
    net_return: Optional[float]
    costs_bps: float
    seed: int
    train_size: int
    test_size: int
    purge: int
    embargo: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WalkForwardSplitter:
    """Expanding-origin walk-forward splits with purge and embargo."""

    def __init__(
        self,
        n_samples: int,
        *,
        train_size: int,
        test_size: int,
        purge: int = 0,
        embargo: int = 0,
    ) -> None:
        if train_size <= 0 or test_size <= 0:
            raise ValueError("train_size and test_size must be positive")
        if purge < 0 or embargo < 0:
            raise ValueError("purge and embargo must be non-negative")
        if n_samples < train_size + purge + test_size:
            raise ValueError("not enough samples for one walk-forward fold")
        self.n_samples = n_samples
        self.train_size = train_size
        self.test_size = test_size
        self.purge = purge
        self.embargo = embargo

    def split(self) -> list[Fold]:
        folds: list[Fold] = []
        test_start = self.train_size + self.purge
        while test_start + self.test_size <= self.n_samples:
            test_end = test_start + self.test_size
            train_end = test_start - self.purge
            train_start = train_end - self.train_size
            folds.append(
                Fold(
                    train_start=train_start,
                    train_end=train_end,
                    test_start=test_start,
                    test_end=test_end,
                )
            )
            test_start = test_end + self.embargo
        return folds


def _check_timestamps(timestamps: Sequence[datetime]) -> None:
    previous: Optional[datetime] = None
    for index, stamp in enumerate(timestamps):
        if previous is not None and stamp <= previous:
            raise LeakDetected(
                "timestamps must be strictly increasing; "
                f"index {index} is not after its predecessor"
            )
        previous = stamp


class WalkForwardBacktester:
    """Deterministic walk-forward evaluation with explicit costs.

    The backtester reports probabilities and a simple long/short return series
    when realized returns are supplied. It makes no alpha claim: costs, purge,
    and embargo are required parts of the report, not hidden defaults.
    """

    def __init__(
        self,
        model_factory: Callable[[], Any],
        *,
        train_size: int,
        test_size: int,
        purge: int = 0,
        embargo: int = 0,
        costs_bps: float = 0.0,
        seed: int = 0,
    ) -> None:
        if costs_bps < 0:
            raise ValueError("costs_bps must be non-negative")
        self.model_factory = model_factory
        self.train_size = train_size
        self.test_size = test_size
        self.purge = purge
        self.embargo = embargo
        self.costs_bps = costs_bps
        self.seed = seed

    def run(
        self,
        features: Sequence[Sequence[float]],
        outcomes: Sequence[float],
        *,
        returns: Optional[Sequence[float]] = None,
        timestamps: Optional[Sequence[datetime]] = None,
    ) -> BacktestReport:
        matrix = np.asarray(features, dtype=float)
        labels = np.asarray(outcomes, dtype=float)
        if matrix.ndim != 2:
            raise ValueError("features must be a 2D array")
        if len(matrix) != len(labels):
            raise ValueError("features and outcomes must align")
        if timestamps is not None:
            if len(timestamps) != len(matrix):
                raise ValueError("timestamps must align with features")
            _check_timestamps(timestamps)
        returns_array: Optional[np.ndarray] = None
        if returns is not None:
            returns_array = np.asarray(returns, dtype=float)
            if len(returns_array) != len(matrix):
                raise ValueError("returns must align with features")

        splitter = WalkForwardSplitter(
            len(matrix),
            train_size=self.train_size,
            test_size=self.test_size,
            purge=self.purge,
            embargo=self.embargo,
        )
        folds = splitter.split()
        if not folds:
            raise ValueError("no walk-forward folds were produced")

        results: list[FoldResult] = []
        predicted: list[float] = []
        realized: list[float] = []
        gross_returns: list[float] = []
        net_returns: list[float] = []
        turnovers: list[float] = []

        for fold in folds:
            if timestamps is not None:
                if timestamps[fold.train_end - 1] >= timestamps[fold.test_start]:
                    raise LeakDetected("train window reaches the test window")
            model = self.model_factory()
            model.fit(
                matrix[fold.train_start : fold.train_end],
                labels[fold.train_start : fold.train_end],
            )
            probabilities = np.asarray(
                model.predict_proba(matrix[fold.test_start : fold.test_end]),
                dtype=float,
            )
            actual = labels[fold.test_start : fold.test_end]
            predicted.extend(float(value) for value in probabilities)
            realized.extend(float(value) for value in actual)

            gross: Optional[float] = None
            net: Optional[float] = None
            turnover: Optional[float] = None
            if returns_array is not None:
                positions = np.where(probabilities >= 0.5, 1.0, -1.0)
                fold_returns = returns_array[fold.test_start : fold.test_end]
                gross = float(np.mean(positions * fold_returns))
                changes = np.abs(np.diff(np.concatenate([[0.0], positions])))
                turnover = float(np.mean(changes))
                net = gross - turnover * self.costs_bps / 10000.0
                gross_returns.append(gross)
                net_returns.append(net)
                turnovers.append(turnover)

            results.append(
                FoldResult(
                    fold=fold,
                    train_samples=fold.train_end - fold.train_start,
                    test_samples=fold.test_end - fold.test_start,
                    brier=float(brier_score(probabilities.tolist(), actual.tolist())),
                    log_loss=float(log_loss(probabilities.tolist(), actual.tolist())),
                    accuracy=float(np.mean((probabilities >= 0.5) == (actual >= 0.5))),
                    gross_return=gross,
                    net_return=net,
                    turnover=turnover,
                )
            )

        return BacktestReport(
            folds=results,
            brier=float(brier_score(predicted, realized)),
            log_loss=float(log_loss(predicted, realized)),
            accuracy=float(
                np.mean(
                    (np.asarray(predicted) >= 0.5)
                    == (np.asarray(realized) >= 0.5)
                )
            ),
            gross_return=float(np.mean(gross_returns)) if gross_returns else None,
            net_return=float(np.mean(net_returns)) if net_returns else None,
            costs_bps=float(self.costs_bps),
            seed=self.seed,
            train_size=self.train_size,
            test_size=self.test_size,
            purge=self.purge,
            embargo=self.embargo,
        )
