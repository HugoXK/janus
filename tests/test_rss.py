from __future__ import annotations

from datetime import datetime, timezone

import httpx

from janus.data.rss import RSSSource, canonical_url

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


def _handler(request: httpx.Request) -> httpx.Response:
    if str(request.url).endswith("/atom"):
        return httpx.Response(200, text=ATOM)
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
