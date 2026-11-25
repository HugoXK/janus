from __future__ import annotations

from datetime import datetime, timezone

import httpx

from janus.data.rss import RSSSource, canonical_url
from janus.data.scheduler import IngestionScheduler
from janus.memory.store import JanusStore

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>ACME wins a contract</title>
    <link>https://example.com/a#section</link>
    <pubDate>Fri, 02 Jan 2026 12:00:00 GMT</pubDate>
    <description>ACME wins</description>
  </item>
  <item>
    <title>ACME wins a contract (duplicate)</title>
    <link>https://example.com/a</link>
    <pubDate>Fri, 02 Jan 2026 12:00:00 GMT</pubDate>
  </item>
  <item>
    <title>Old story</title>
    <link>https://example.com/old</link>
    <pubDate>Thu, 01 Jan 2025 12:00:00 GMT</pubDate>
  </item>
</channel></rss>
"""

ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>ACME atom</title>
    <link href="https://example.com/atom"/>
    <updated>2026-01-02T12:00:00Z</updated>
    <summary>Atom summary</summary>
  </entry>
</feed>
"""


RDF = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns="http://purl.org/rss/1.0/"
         xmlns:dc="http://purl.org/dc/elements/1.1/">
  <item rdf:about="https://example.com/rdf">
    <title>ACME rdf</title>
    <link>https://example.com/rdf</link>
    <dc:date>2026-01-02T12:00:00Z</dc:date>
  </item>
</rdf:RDF>
"""


def _handler(request: httpx.Request) -> httpx.Response:
    if str(request.url).endswith("/atom"):
        return httpx.Response(200, text=ATOM)
    if str(request.url).endswith("/rdf"):
        return httpx.Response(200, text=RDF)
    return httpx.Response(200, text=RSS)


def test_rss_and_atom_dedup_by_canonical_url() -> None:
    source = RSSSource(
        ["https://example.com/rss", "https://example.com/atom"],
        client=httpx.Client(transport=httpx.MockTransport(_handler)),
    )
    rows = source.fetch(
        "ACME",
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 3, tzinfo=timezone.utc),
    )

    assert len(rows) == 2
    urls = {row.value["url"] for row in rows}
    assert urls == {"https://example.com/a", "https://example.com/atom"}
    assert all(row.value["title"] for row in rows)


def test_canonical_url_strips_fragment_and_normalizes_host() -> None:
    assert canonical_url("HTTPS://Example.COM/a#frag") == "https://example.com/a"


def test_shared_feed_keeps_entities_separate() -> None:
    source = RSSSource(
        ["https://example.com/rss"],
        client=httpx.Client(transport=httpx.MockTransport(_handler)),
    )
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 3, tzinfo=timezone.utc)
    acme = source.fetch("ACME", start, end)
    beta = source.fetch("BETA", start, end)

    assert acme[0].id != beta[0].id
    assert acme[0].id.startswith("rss:ACME:")
    assert beta[0].id.startswith("rss:BETA:")

    store = JanusStore(":memory:")
    IngestionScheduler(store).run(source, ["ACME", "BETA"], start, end)
    assert store.get_observation(acme[0].id) is not None
    assert store.get_observation(beta[0].id) is not None


def test_rss_1_0_rdf_is_supported() -> None:
    source = RSSSource(
        ["https://example.com/rdf"],
        client=httpx.Client(transport=httpx.MockTransport(_handler)),
    )
    rows = source.fetch(
        "ACME",
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 3, tzinfo=timezone.utc),
    )
    assert [row.value["url"] for row in rows] == ["https://example.com/rdf"]
    assert rows[0].published_at == datetime(2026, 1, 2, 12, tzinfo=timezone.utc)
