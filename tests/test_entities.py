from __future__ import annotations

import json
import sqlite3

import pytest
from typer.testing import CliRunner

from janus.cli import app

from janus.memory.entities import Entity, EntityGraph
from janus.memory.store import JanusStore


def test_entity_graph_resolves_ticker_cik_and_names() -> None:
    store = JanusStore(":memory:")
    graph = EntityGraph(store)
    graph.upsert(
        Entity(
            id="apple",
            name="Apple Inc.",
            ticker="AAPL",
            cik="0000320193",
            sector="Technology",
            industry="Consumer Electronics",
        )
    )
    graph.add_alias("AAPL", "apple", source="ticker")
    graph.add_alias("Apple", "apple", source="name")
    graph.add_alias("Apple Inc.", "apple", source="name")

    for alias in ("AAPL", "aapl", "Apple", "apple inc."):
        resolved = graph.resolve(alias)
        assert resolved is not None
        assert resolved.id == "apple"

    assert graph.get("apple").cik == "0000320193"
    assert len(graph.aliases("apple")) == 3
    assert graph.resolve("MSFT") is None


def test_alias_can_be_reassigned() -> None:
    store = JanusStore(":memory:")
    graph = EntityGraph(store)
    graph.upsert(Entity(id="old", name="Old Co"))
    graph.upsert(Entity(id="new", name="New Co"))
    graph.add_alias("TICK", "old")

    graph.add_alias("TICK", "new")

    assert graph.resolve("tick").id == "new"


def test_alias_to_unknown_entity_is_rejected() -> None:
    store = JanusStore(":memory:")
    graph = EntityGraph(store)

    with pytest.raises(sqlite3.IntegrityError):
        graph.add_alias("TICK", "missing")


def test_entity_cli_resolve_show_list(tmp_path, monkeypatch) -> None:
    path = tmp_path / "janus.db"
    graph = EntityGraph(JanusStore(path))
    graph.upsert(
        Entity(
            id="apple",
            name="Apple Inc.",
            ticker="AAPL",
            cik="0000320193",
        )
    )
    graph.add_alias("AAPL", "apple", source="ticker")
    graph.add_alias("Apple", "apple", source="name")
    monkeypatch.setenv("JANUS_DB", str(path))
    runner = CliRunner()

    resolved = runner.invoke(app, ["entity", "resolve", "Apple", "--json"])
    assert resolved.exit_code == 0, resolved.output
    assert json.loads(resolved.output)["id"] == "apple"

    shown = runner.invoke(app, ["entity", "show", "apple", "--json"])
    assert shown.exit_code == 0, shown.output
    assert len(json.loads(shown.output)["aliases"]) == 2

    listed = runner.invoke(app, ["entity", "list", "--json"])
    assert listed.exit_code == 0, listed.output
    assert json.loads(listed.output)[0]["id"] == "apple"

    missing = runner.invoke(app, ["entity", "resolve", "MSFT"])
    assert missing.exit_code == 1


def test_entity_cli_rejects_a_negative_limit(tmp_path, monkeypatch) -> None:
    path = tmp_path / "janus.db"
    EntityGraph(JanusStore(path))
    monkeypatch.setenv("JANUS_DB", str(path))
    runner = CliRunner()

    zero = runner.invoke(app, ["entity", "list", "--limit", "0"])
    assert zero.exit_code == 0, zero.output
    assert "no entities" in zero.output

    bad = runner.invoke(app, ["entity", "list", "--limit", "-1"])
    assert bad.exit_code != 0
    combined = bad.output + getattr(bad, "stderr", "")
    assert "limit must be >= 0" in combined
    assert "Traceback" not in combined
