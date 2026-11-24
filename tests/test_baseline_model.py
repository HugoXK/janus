from __future__ import annotations

import numpy as np
import pytest

from janus.forecast.baseline import LogisticDirectionModel


def _data() -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(7)
    features = np.column_stack(
        [
            rng.uniform(0, 100, 300),
            rng.uniform(-1, 1, 300),
            rng.uniform(0, 1, 300),
        ]
    )
    score = (
        (features[:, 0] - 50.0) / 50.0 * 0.4
        + features[:, 1] * 0.4
        + (features[:, 2] - 0.5) * 0.4
    )
    outcomes = (score > 0).astype(float)
    return features, outcomes


def test_fit_predict_and_round_trip() -> None:
    features, outcomes = _data()
    model = LogisticDirectionModel(epochs=800)
    card = model.fit(features, outcomes)

    assert card.training_samples == 300
    assert card.version == "logit-v1"
    assert model.predict_one(rsi_value=85, trend=0.8, breadth=0.8) > 0.5
    assert model.predict_one(rsi_value=15, trend=-0.8, breadth=0.2) < 0.5
    assert all(0.0 <= value <= 1.0 for value in model.predict_proba(features[:5]))

    clone = LogisticDirectionModel.from_dict(model.to_dict())
    assert clone.predict_one(rsi_value=85, trend=0.8, breadth=0.8) == pytest.approx(
        model.predict_one(rsi_value=85, trend=0.8, breadth=0.8)
    )


def test_unfitted_model_fails_loudly() -> None:
    with pytest.raises(RuntimeError):
        LogisticDirectionModel().predict_one(rsi_value=50, trend=0.0, breadth=0.5)
