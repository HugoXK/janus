from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from janus.data.base import DataUnavailable
from janus.data.fred import FREDSource
from janus.memory.models import ObservationKind


def _handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "/series/observations?" in url:
        if "realtime_start=2026-01-15" in url:
            return httpx.Response(
                200,
                json={
                    "observations": [
                        {
                            "date": "2026-01-02",
                            "value": "4.25",
                            "realtime_start": "2026-01-15",
                            "realtime_end": "2026-01-15",
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "observations": [
                    {
                        "date": "2026-01-02",
                        "value": "4.25",
                        "realtime_start": "2026-01-02",
                        "realtime_end": "2026-01-02",
                    },
                    {
                        "date": "2026-01-03",
                        "value": ".",
                        "realtime_start": "2026-01-03",
                        "realtime_end": "2026-01-03",
                    },
                ]
            },
        )
    if "/series?" in url:
        return httpx.Response(200, json={"seriess": [{"id": "DGS10", "units": "Percent"}]})
    return httpx.Response(404)


def _source(**kwargs) -> FREDSource:
    return FREDSource(
        api_key="test-key",
        client=httpx.Client(transport=httpx.MockTransport(_handler)),
        **kwargs,
    )


def test_fred_latest_observation_skips_missing_values() -> None:
    source = _source()
    rows = source.fetch(
        "DGS10",
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 5, tzinfo=timezone.utc),
    )

    assert len(rows) == 1
    observation = rows[0]
    assert observation.kind is ObservationKind.macro
    assert observation.value["value"] == 4.25
    assert observation.unit == "Percent"
    assert observation.published_at.date().isoformat() == "2026-01-03"
    assert "api_key" not in (observation.raw_uri or "")


def test_fred_vintage_uses_the_vintage_date_as_publication() -> None:
    source = _source(vintage="2026-01-15")
    rows = source.fetch(
        "DGS10",
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 5, tzinfo=timezone.utc),
    )

    assert len(rows) == 1
    observation = rows[0]
    assert observation.published_at.date().isoformat() == "2026-01-15"
    assert observation.value["vintage"] == "2026-01-15"


def test_fred_missing_key_is_explicit() -> None:
    source = FREDSource(
        api_key=None,
        client=httpx.Client(transport=httpx.MockTransport(_handler)),
    )
    with pytest.raises(DataUnavailable, match="FRED_API_KEY"):
        source.fetch(
            "DGS10",
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 5, tzinfo=timezone.utc),
        )
