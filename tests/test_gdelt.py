from __future__ import annotations

from datetime import datetime, timezone

import httpx

from janus.data.gdelt import GDELTSource
from janus.memory.models import ObservationKind

ARTICLES = {
    "articles": [
        {
            "url": "https://example.com/a",
            "title": "ACME wins a contract",
            "seendate": "20260102T120000Z",
            "domain": "example.com",
            "language": "English",
            "sourcecountry": "United States",
        },
        {
            "url": "https://example.com/a",
            "title": "ACME wins a contract (duplicate)",
            "seendate": "20260102T120000Z",
            "domain": "example.com",
            "language": "English",
            "sourcecountry": "United States",
        },
        {
            "url": "https://example.com/b",
            "title": "Bad date",
            "seendate": "not-a-date",
            "domain": "example.com",
        },
    ]
}


def _handler(request: httpx.Request) -> httpx.Response:
    assert "format=json" in str(request.url)
    return httpx.Response(200, json=ARTICLES)


def test_fetch_dedups_and_parses_articles() -> None:
    source = GDELTSource(client=httpx.Client(transport=httpx.MockTransport(_handler)))
    rows = source.fetch(
        "ACME",
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 3, tzinfo=timezone.utc),
    )

    assert len(rows) == 1
    observation = rows[0]
    assert observation.kind is ObservationKind.news
    assert observation.source == "gdelt"
    assert observation.value["title"] == "ACME wins a contract"
    assert observation.published_at == datetime(2026, 1, 2, 12, tzinfo=timezone.utc)
    assert observation.id.startswith("gdelt:ACME:")
