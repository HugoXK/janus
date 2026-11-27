from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from typer.testing import CliRunner

from janus.cli import app
from janus.memory.security_master import Membership, Security, SecurityMaster
from janus.memory.store import JanusStore

runner = CliRunner()


def _dt(day: int) -> datetime:
    return datetime(2026, 1, day, tzinfo=timezone.utc)


def _seed() -> SecurityMaster:
    graph = SecurityMaster(JanusStore(":memory:"))
    graph.add_security(
        Security(id="old", entity_id="OLD", symbol="XYZ", valid_from=_dt(1), valid_to=_dt(10))
    )
    graph.add_security(
        Security(
            id="new",
            entity_id="NEW",
            symbol="XYZ",
            valid_from=_dt(10),
            exchange="NASDAQ",
        )
    )
    graph.add_security(
        Security(id="other", entity_id="OTHER", symbol="ABC", valid_from=_dt(1))
    )
    graph.add_membership(
        Membership(universe="SPX", security_id="old", valid_from=_dt(1), valid_to=_dt(10))
    )
    graph.add_membership(
        Membership(universe="SPX", security_id="new", valid_from=_dt(10))
    )
    graph.add_membership(
        Membership(universe="SPX", security_id="other", valid_from=_dt(1))
    )
    return graph


def test_symbol_reuse_resolves_by_as_of() -> None:
    graph = _seed()
    assert graph.resolve("xyz", _dt(5)).id == "old"  # type: ignore[union-attr]
    assert graph.resolve("XYZ", _dt(15)).id == "new"  # type: ignore[union-attr]
    assert graph.resolve("XYZ", _dt(10), exchange="NASDAQ").id == "new"  # type: ignore[union-attr]
    assert graph.resolve("XYZ", _dt(10), exchange="NYSE") is None
    assert len(graph.history("xyz")) == 2


def test_universe_members_are_point_in_time() -> None:
    graph = _seed()
    assert {row.id for row in graph.members("SPX", _dt(5))} == {"old", "other"}
    members = graph.members("SPX", _dt(15))
    assert {row.id for row in members} == {"new", "other"}
    assert graph.members("SPX", _dt(10))[0].id in {"new", "other"}


def test_membership_requires_a_known_security() -> None:
    graph = SecurityMaster(JanusStore(":memory:"))
    with pytest.raises(KeyError, match="unknown security"):
        graph.add_membership(Membership(universe="SPX", security_id="missing", valid_from=_dt(1)))


def test_invalid_windows_and_naive_times_are_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        Security(id="x", entity_id="X", symbol="X", valid_from=datetime(2026, 1, 1))
    with pytest.raises(ValueError, match="after valid_from"):
        Security(
            id="x",
            entity_id="X",
            symbol="X",
            valid_from=_dt(2),
            valid_to=_dt(1),
        )


def test_security_cli_resolve_and_universe_members(tmp_path, monkeypatch) -> None:
    path = tmp_path / "janus.db"
    store = JanusStore(path)
    graph = SecurityMaster(store)
    graph.add_security(Security(id="new", entity_id="NEW", symbol="XYZ", valid_from=_dt(10)))
    graph.add_membership(Membership(universe="SPX", security_id="new", valid_from=_dt(10)))
    monkeypatch.setenv("JANUS_DB", str(path))

    resolved = runner.invoke(
        app, ["security", "resolve", "XYZ", "--as-of", "2026-01-15T00:00:00+00:00", "--json"]
    )
    assert resolved.exit_code == 0, resolved.output
    assert json.loads(resolved.output)["id"] == "new"

    members = runner.invoke(
        app, ["universe", "members", "SPX", "--as-of", "2026-01-15T00:00:00+00:00", "--json"]
    )
    assert members.exit_code == 0, members.output
    assert json.loads(members.output)[0]["id"] == "new"
