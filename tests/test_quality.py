from __future__ import annotations

from datetime import datetime, timezone

from janus.data.quality import check_observations
from janus.memory.models import Observation, ObservationKind


def _observation(
    obs_id: str = "px-1",
    *,
    close: float = 100.0,
    published_at: datetime | None = None,
) -> Observation:
    return Observation(
        id=obs_id,
        entity_id="ACME",
        kind=ObservationKind.price,
        source="test",
        published_at=published_at or datetime(2026, 1, 1, tzinfo=timezone.utc),
        value={"close": close},
        raw_hash=f"hash:{obs_id}",
    )


def test_valid_observation_has_no_errors() -> None:
    report = check_observations(
        [_observation()],
        as_of=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    assert report.ok
    assert report.errors == ()


def test_duplicate_and_non_positive_price_are_errors() -> None:
    report = check_observations(
        [_observation("dup", close=-1), _observation("dup", close=10)],
        as_of=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    codes = {issue.code for issue in report.errors}
    assert "duplicate_id" in codes
    assert "non_positive_price" in codes


def test_future_timestamp_is_an_error() -> None:
    future = _observation(
        "future", published_at=datetime(2026, 1, 10, tzinfo=timezone.utc)
    )
    report = check_observations(
        [future], as_of=datetime(2026, 1, 5, tzinfo=timezone.utc)
    )
    assert any(issue.code == "future_timestamp" for issue in report.errors)


def test_stale_feed_is_a_warning() -> None:
    stale = _observation(
        "stale", published_at=datetime(2025, 12, 1, tzinfo=timezone.utc)
    )
    report = check_observations(
        [stale],
        as_of=datetime(2026, 1, 5, tzinfo=timezone.utc),
        max_age_days=7,
    )
    assert any(issue.code == "stale_feed" for issue in report.warnings)
