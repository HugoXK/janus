from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from typer.testing import CliRunner

from janus.cli import app
from janus.memory.models import Observation, ObservationKind
from janus.memory.spans import SourceSpan, SpanStore
from janus.memory.store import JanusStore

runner = CliRunner()


def _store() -> JanusStore:
    store = JanusStore(":memory:")
    store.insert_observation(
        Observation(
            id="news",
            entity_id="ACME",
            kind=ObservationKind.news,
            source="sec_edgar",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            value={"title": "10-K"},
            raw_hash="blob-1",
            raw_uri="https://www.sec.gov/example.htm",
        )
    )
    return store


def test_add_list_and_citation() -> None:
    store = _store()
    spans = SpanStore(store)
    spans.add(
        SourceSpan(
            id="span-1",
            observation_id="news",
            blob_hash="blob-1",
            locator="page=12;paragraph=3",
            excerpt="Revenue grew 12%.",
            start_offset=100,
            end_offset=117,
        )
    )
    assert [span.id for span in spans.list("news")] == ["span-1"]
    citation = spans.citation("news")
    assert citation.span_id == "span-1"
    assert citation.locator == "page=12;paragraph=3"
    assert "sec_edgar" in citation.text
    assert "sec.gov" in citation.text
    assert "page=12" in citation.text


def test_missing_span_and_blob_mismatch_are_explicit() -> None:
    store = _store()
    spans = SpanStore(store)
    with pytest.raises(KeyError, match="no source span"):
        spans.citation("news")
    with pytest.raises(KeyError, match="unknown observation"):
        spans.add(
            SourceSpan(
                id="bad",
                observation_id="missing",
                blob_hash="x",
                locator="p=1",
                excerpt="x",
            )
        )
    with pytest.raises(ValueError, match="raw_hash"):
        spans.add(
            SourceSpan(
                id="bad",
                observation_id="news",
                blob_hash="other",
                locator="p=1",
                excerpt="x",
            )
        )


def test_span_validation() -> None:
    with pytest.raises(ValueError, match="locator"):
        SourceSpan(id="x", observation_id="o", blob_hash="b", locator="", excerpt="x")
    with pytest.raises(ValueError, match="excerpt"):
        SourceSpan(id="x", observation_id="o", blob_hash="b", locator="p", excerpt=" ")
    with pytest.raises(ValueError, match="end_offset"):
        SourceSpan(
            id="x",
            observation_id="o",
            blob_hash="b",
            locator="p",
            excerpt="x",
            start_offset=10,
            end_offset=5,
        )


def test_cli_spans_and_citation(tmp_path, monkeypatch) -> None:
    path = tmp_path / "janus.db"
    store = JanusStore(path)
    store.insert_observation(
        Observation(
            id="news",
            entity_id="ACME",
            kind=ObservationKind.news,
            source="rss",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            value={"title": "story"},
            raw_hash="blob-1",
        )
    )
    SpanStore(store).add(
        SourceSpan(
            id="span-1",
            observation_id="news",
            blob_hash="blob-1",
            locator="p=1",
            excerpt="exact words",
        )
    )
    monkeypatch.setenv("JANUS_DB", str(path))

    listed = runner.invoke(app, ["spans", "list", "news", "--json"])
    assert listed.exit_code == 0, listed.output
    assert json.loads(listed.output)[0]["id"] == "span-1"

    cited = runner.invoke(app, ["citation", "news", "--json"])
    assert cited.exit_code == 0, cited.output
    assert json.loads(cited.output)["span_id"] == "span-1"

    missing = runner.invoke(app, ["citation", "other"])
    assert missing.exit_code == 1
