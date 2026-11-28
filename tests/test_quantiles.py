from __future__ import annotations

import numpy as np
import pytest

from janus.forecast.quantiles import EmpiricalQuantileModel


def test_quantiles_are_sorted_and_scale_with_horizon() -> None:
    model = EmpiricalQuantileModel().fit(np.linspace(-0.05, 0.05, 101))
    one_day = model.predict()
    ten_day = model.predict(horizon=10)

    assert list(one_day.quantiles) == ["0.10", "0.50", "0.90"]
    values = [one_day.quantiles[key] for key in one_day.quantiles]
    assert values == sorted(values)
    assert ten_day.width == pytest.approx(one_day.width * np.sqrt(10))


def test_intervals_widen_with_volatility() -> None:
    calm = EmpiricalQuantileModel().fit(np.linspace(-0.01, 0.01, 201))
    volatile = EmpiricalQuantileModel().fit(np.linspace(-0.05, 0.05, 201))
    assert volatile.predict().width > calm.predict().width


def test_empirical_coverage_is_close_to_the_level() -> None:
    rng = np.random.default_rng(11)
    history = rng.normal(0.0, 0.02, 4000)
    outcomes = rng.normal(0.0, 0.02, 1000)
    model = EmpiricalQuantileModel().fit(history)
    coverage = model.coverage(outcomes)
    assert 0.75 <= coverage <= 0.85


def test_fit_requires_enough_finite_returns() -> None:
    with pytest.raises(ValueError, match="two finite"):
        EmpiricalQuantileModel().fit([np.nan, 0.01])
    with pytest.raises(RuntimeError):
        EmpiricalQuantileModel().predict()
