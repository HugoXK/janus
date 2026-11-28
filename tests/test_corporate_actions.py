from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from typer.testing import CliRunner

from janus.cli import app
from janus.memory.corporate_actions import CorporateAction, CorporateActionLedger
from janus.memory.store import JanusStore

runner = CliRunner()


def _dt(day: int) -> datetime:
    return datetime(2026, 1, day, tzinfo=timezone.utc)


def _ledger() -> CorporateActionLedger:
    ledger = CorporateActionLedger(JanusStore(":memory:"))
    ledger.add(
        CorporateAction(
            id="split-1",
            security_id="ACME",
            action_type="split",
            effective_at=_dt(10),
            ratio=2.0,
            source="test",
        )
    )
    ledger.add(
        CorporateAction(
            id="div-1",
            security_id="ACME",
            action_type="cash_dividend",
            effective_at=_dt(15),
            cash_amount=0.5,
            currency="USD",
            source="test",
        )
    )
    ledger.add(
        CorporateAction(
            id="merge-1",
            security_id="ACME",
            action_type="merger",
            effective_at=_dt(20),
            related_security_id="BETA",
            source="test",
        )
    )
    return ledger


def test_split_and_dividend_basis() -> None:
    ledger = _ledger()
    adjustment = ledger.adjustment("ACME", _dt(18))
    assert adjustment.split_factor == 2.0
    assert adjustment.cash_dividends == 0.5
    assert adjustment.action_ids == ("split-1", "div-1")
    assert adjustment.manual_action_ids == ()
    assert "split:2" in adjustment.basis
    assert "cash_dividend:0.5" in adjustment.basis

    payload = ledger.adjust_price("ACME", 100.0, _dt(18))
    assert payload["adjusted_price"] == 50.0
    assert payload["manual_action_ids"] == []


def test_as_of_excludes_future_actions() -> None:
    ledger = _ledger()
    assert ledger.list("ACME", as_of=_dt(12))[0].id == "split-1"
    assert ledger.adjustment("ACME", _dt(12)).split_factor == 2.0
    assert ledger.adjustment("ACME", _dt(1)).split_factor == 1.0


def test_manual_actions_are_flagged_not_silently_applied() -> None:
    ledger = _ledger()
    adjustment = ledger.adjustment("ACME", _dt(25))
    assert adjustment.manual_action_ids == ("merge-1",)
    assert "manual:merge-1" in adjustment.basis
    assert adjustment.split_factor == 2.0


def test_action_validation() -> None:
    with pytest.raises(ValueError, match="unknown action type"):
        CorporateAction(
            id="bad", security_id="X", action_type="mystery", effective_at=_dt(1)
        )
    with pytest.raises(ValueError, match="positive ratio"):
        CorporateAction(
            id="bad", security_id="X", action_type="split", effective_at=_dt(1)
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        CorporateAction(
            id="bad",
            security_id="X",
            action_type="split",
            effective_at=datetime(2026, 1, 1),
            ratio=2.0,
        )
    with pytest.raises(ValueError, match="related_security_id"):
        CorporateAction(
            id="bad", security_id="X", action_type="merger", effective_at=_dt(1)
        )


def test_actions_cli_list_and_adjust(tmp_path, monkeypatch) -> None:
    path = tmp_path / "janus.db"
    ledger = CorporateActionLedger(JanusStore(path))
    ledger.add(
        CorporateAction(
            id="split-1",
            security_id="ACME",
            action_type="split",
            effective_at=_dt(10),
            ratio=2.0,
        )
    )
    monkeypatch.setenv("JANUS_DB", str(path))

    listed = runner.invoke(
        app,
        ["actions", "list", "--security", "ACME", "--as-of", "2026-01-20T00:00:00+00:00", "--json"],
    )
    assert listed.exit_code == 0, listed.output
    assert json.loads(listed.output)[0]["id"] == "split-1"

    adjusted = runner.invoke(
        app,
        [
            "actions",
            "adjust",
            "ACME",
            "--price",
            "100",
            "--as-of",
            "2026-01-20T00:00:00+00:00",
            "--json",
        ],
    )
    assert adjusted.exit_code == 0, adjusted.output
    payload = json.loads(adjusted.output)
    assert payload["adjusted_price"] == 50.0
    assert payload["basis"] == "split:2"
