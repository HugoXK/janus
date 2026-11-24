from __future__ import annotations

from datetime import datetime, timedelta, timezone

from janus.memory.models import Observation, ObservationKind
from janus.memory.provenance import ProvenanceTracer
from janus.memory.store import JanusStore


def test_trace_and_search_respect_as_of() -> None:
    store = JanusStore(":memory:")
    as_of = datetime(2026, 1, 10, tzinfo=timezone.utc)
    observation = Observation(
        id="news-1",
        entity_id="ACME",
        kind=ObservationKind.news,
        source="rss",
        published_at=as_of - timedelta(days=1),
        value={"headline": "ACME wins a contract"},
        raw_hash="hash-1",
        raw_uri="https://example.com/news/1",
    )
    store.insert_observation(observation)

    tracer = ProvenanceTracer(store)
    traced = tracer.trace("news-1")
    assert traced is not None
    assert traced.observation.id == "news-1"
    assert "rss" in traced.citation
    assert "example.com" in traced.citation
    assert tracer.trace("missing") is None

    found = tracer.search("ACME", "contract", as_of)
    assert [item.observation.id for item in found] == ["news-1"]

    before_publication = as_of - timedelta(days=2)
    assert tracer.search("ACME", "contract", before_publication) == []
