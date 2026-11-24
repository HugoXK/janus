from __future__ import annotations

import sqlite3

import pytest

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
