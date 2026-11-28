from __future__ import annotations

from datetime import datetime, timedelta, timezone

from janus.memory.models import Observation, ObservationKind
import json

import pytest
from typer.testing import CliRunner

from janus.cli import app
from janus.memory.provenance import ProvenanceError, ProvenanceTracer
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


def test_require_and_catalog_make_missing_spans_explicit() -> None:
    store = JanusStore(":memory:")
    as_of = datetime(2026, 1, 10, tzinfo=timezone.utc)
    store.insert_observation(
        Observation(
            id="news-1",
            entity_id="ACME",
            kind=ObservationKind.news,
            source="rss",
            published_at=as_of,
            value={"headline": "ACME wins"},
            raw_hash="hash-1",
            raw_uri="https://example.com/news/1",
        )
    )
    tracer = ProvenanceTracer(store)
    traced = tracer.require("news-1")
    assert traced.to_dict()["observation"]["id"] == "news-1"
    assert tracer.catalog()[0].observation.id == "news-1"
    with pytest.raises(ProvenanceError, match="observation not found"):
        tracer.require("missing")


def test_cli_provenance_json_and_missing(tmp_path, monkeypatch) -> None:
    path = tmp_path / "janus.db"
    store = JanusStore(path)
    store.insert_observation(
        Observation(
            id="news-1",
            entity_id="ACME",
            kind=ObservationKind.news,
            source="rss",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            value={"headline": "ACME wins"},
            raw_hash="hash-1",
        )
    )
    monkeypatch.setenv("JANUS_DB", str(path))
    runner = CliRunner()

    result = runner.invoke(app, ["provenance", "news-1", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["observation"]["id"] == "news-1"
    assert "rss" in payload["citation"]

    missing = runner.invoke(app, ["provenance", "missing"])
    assert missing.exit_code == 1
    assert "observation not found" in missing.output
