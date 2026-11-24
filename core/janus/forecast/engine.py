from __future__ import annotations

import math


def baseline_direction_probability(
    *,
    rsi_value: float,
    trend: float,
    breadth: float,
) -> float:
    """A deliberately simple baseline forecaster.

    Inputs:
    - ``rsi_value``: 0-100
    - ``trend``: -1 to 1 (e.g. normalized distance from a moving average)
    - ``breadth``: 0 to 1 (share of names above their moving average)

    The output is a probability in [0, 1], not a price target. Replace this with
    a calibrated model once the forecast ledger has enough outcomes.
    """

    score = (
        0.4 * ((rsi_value - 50.0) / 50.0)
        + 0.4 * max(-1.0, min(1.0, trend))
        + 0.2 * (2.0 * (breadth - 0.5))
    )
    return 1.0 / (1.0 + math.exp(-score))
