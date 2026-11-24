from __future__ import annotations

from datetime import datetime
from typing import Callable, Iterable, Any


def walk_forward(
    *,
    dates: Iterable[datetime],
    fit: Callable[[list[datetime]], Any],
    predict: Callable[[Any, datetime], dict[str, float]],
    min_train: int = 60,
    step: int = 1,
) -> list[dict[str, Any]]:
    """Minimal walk-forward loop.

    The full engine will add purging/embargo, transaction costs, survivorship
    handling, and multiple-testing corrections. This skeleton exists so the
    interface is fixed early.
    """

    ordered = list(dates)
    if len(ordered) <= min_train:
        raise ValueError("not enough dates for the requested min_train window")

    results: list[dict[str, Any]] = []
    for index in range(min_train, len(ordered), step):
        train = ordered[:index]
        as_of = ordered[index]
        model = fit(train)
        results.append({"as_of": as_of, "forecast": predict(model, as_of)})
    return results
