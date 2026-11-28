from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from janus.cli import app
from janus.forecast.ledger import PredictionLedger
from janus.memory.audit import (
    AuditChain,
    AuditError,
    ChainGapError,
    CheckpointMismatchError,
    EntryHashError,
    SourceDriftError,
    SourceMissingError,
)
from janus.memory.store import JanusStore
from janus.thesis.tracker import ThesisTracker

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _thesis(store: JanusStore):
    return ThesisTracker(store).create(
        entity_id="ACME",
        statement="ACME holds its trend.",
        horizon="1M",
        as_of=T0,
    )


def _prediction(store: JanusStore):
    ledger = PredictionLedger(store)
    prediction = ledger.record(
        thesis_id=_thesis(store).id,
        target="direction",
        horizon="1M",
        as_of=T0,
        model_version="baseline-0.1",
        features_hash="abc",
        probability=0.7,
    )
    return ledger, prediction


def _drop_guard(store: JanusStore) -> None:
    store.connection.execute("DROP TRIGGER audit_entry_no_update")
    store.connection.execute("DROP TRIGGER audit_entry_no_delete")


def test_ledger_records_prediction_and_outcome_in_the_chain() -> None:
    store = JanusStore(":memory:")
    ledger, prediction = _prediction(store)
    ledger.settle(
        prediction.id,
        realized_value={"direction": "up"},
        source="test",
        realized_at=T0 + timedelta(days=30),
        score=1.0,
    )

    chain = AuditChain(store)
    entries = chain.entries()
    assert [entry.kind for entry in entries] == ["prediction", "outcome"]
    assert entries[0].ref_id == prediction.id
    assert entries[1].payload["prediction_id"] == prediction.id
    assert entries[0].prev_hash == AuditChain.GENESIS
    assert entries[1].prev_hash == entries[0].entry_hash

    report = chain.verify()
    assert report.count == 2
    assert report.head_hash == entries[-1].entry_hash


def test_identical_events_hash_identically_and_order_is_by_seq() -> None:
    payload = {"entity_id": "ACME", "value": 1.5}

    first = AuditChain(JanusStore(":memory:"))
    first.append("share", "bundle-1", payload, recorded_at=T0)
    second = AuditChain(JanusStore(":memory:"))
    second.append("share", "bundle-1", payload, recorded_at=T0)

    assert first.head().head_hash == second.head().head_hash

    # Later events may carry an earlier recorded_at; ordering stays by seq.
    first.append("override", "bundle-1", {"reason": "manual"}, recorded_at=T0 - timedelta(days=1))
    assert [entry.seq for entry in first.entries()] == [1, 2]
    assert [entry.kind for entry in first.entries()] == ["share", "override"]


def test_rewritten_entry_is_detected() -> None:
    store = JanusStore(":memory:")
    chain = AuditChain(store)
    chain.append("share", "bundle-1", {"rows": 1}, recorded_at=T0)
    chain.append("share", "bundle-2", {"rows": 2}, recorded_at=T0 + timedelta(minutes=1))

    _drop_guard(store)
    store.connection.execute(
        "UPDATE audit_entry SET payload = ? WHERE seq = 1",
        ('{"rows":99}',),
    )
    store.connection.commit()

    with pytest.raises(EntryHashError):
        chain.verify()


def test_deleted_entry_is_detected_as_a_gap() -> None:
    store = JanusStore(":memory:")
    chain = AuditChain(store)
    for index in range(3):
        chain.append("override", f"p-{index}", {"index": index}, recorded_at=T0)

    _drop_guard(store)
    store.connection.execute("DELETE FROM audit_entry WHERE seq = 2")
    store.connection.commit()

    with pytest.raises(ChainGapError):
        chain.verify()


def test_checkpoint_detects_a_truncated_tail() -> None:
    store = JanusStore(":memory:")
    chain = AuditChain(store)
    chain.append("share", "bundle-1", {"rows": 1}, recorded_at=T0)
    chain.append("share", "bundle-2", {"rows": 2}, recorded_at=T0 + timedelta(minutes=1))
    checkpoint = chain.checkpoint()

    _drop_guard(store)
    store.connection.execute("DELETE FROM audit_entry WHERE seq = 2")
    store.connection.commit()

    # Without an external checkpoint a truncated tail looks valid.
    chain.verify()
    with pytest.raises(CheckpointMismatchError):
        chain.verify(checkpoint=checkpoint)


def test_direct_mutation_is_blocked_by_append_only_triggers() -> None:
    store = JanusStore(":memory:")
    chain = AuditChain(store)
    chain.append("share", "bundle-1", {"rows": 1}, recorded_at=T0)

    with pytest.raises(sqlite3.IntegrityError):
        store.connection.execute("UPDATE audit_entry SET payload = '{}' WHERE seq = 1")
    with pytest.raises(sqlite3.IntegrityError):
        store.connection.execute("DELETE FROM audit_entry WHERE seq = 1")


def test_rewritten_source_row_is_detected() -> None:
    store = JanusStore(":memory:")
    ledger, prediction = _prediction(store)
    store.connection.execute(
        "UPDATE prediction SET probability = 0.99 WHERE id = ?", (prediction.id,)
    )
    store.connection.commit()

    with pytest.raises(SourceDriftError):
        AuditChain(store).verify()


def test_deleted_source_row_is_detected() -> None:
    store = JanusStore(":memory:")
    ledger, prediction = _prediction(store)
    outcome = ledger.settle(
        prediction.id,
        realized_value={"direction": "up"},
        source="test",
        realized_at=T0 + timedelta(days=30),
    )
    store.connection.execute("DELETE FROM outcome WHERE id = ?", (outcome.id,))
    store.connection.commit()

    with pytest.raises(SourceMissingError):
        AuditChain(store).verify()


def test_as_of_returns_a_verified_prefix() -> None:
    store = JanusStore(":memory:")
    chain = AuditChain(store)
    chain.append("share", "b-1", {"n": 1}, recorded_at=T0)
    chain.append("share", "b-2", {"n": 2}, recorded_at=T0 + timedelta(hours=1))
    chain.append("share", "b-3", {"n": 3}, recorded_at=T0 + timedelta(hours=2))

    prefix = chain.entries(as_of=T0 + timedelta(hours=1))
    assert [entry.ref_id for entry in prefix] == ["b-1", "b-2"]
    checkpoint = chain.checkpoint(as_of=T0 + timedelta(hours=1))
    assert checkpoint.count == 2
    assert checkpoint.head_seq == 2


def test_export_round_trip_and_tamper_detection(tmp_path: Path) -> None:
    store = JanusStore(":memory:")
    chain = AuditChain(store)
    _, prediction = _prediction(store)
    chain.record_share("bundle-1", {"prediction_id": prediction.id}, recorded_at=T0)
    chain.record_override(
        prediction.id, {"reason": "manual review", "actor": "owner"}, recorded_at=T0
    )

    target = tmp_path / "audit.json"
    chain.export(target)
    payload = json.loads(target.read_text())
    assert payload["version"] == AuditChain.AUDIT_VERSION
    assert payload["checkpoint"]["count"] == len(chain.entries())
    assert [entry["kind"] for entry in payload["entries"]] == [
        "prediction",
        "share",
        "override",
    ]

    report = AuditChain.verify_export(target)
    assert report.count == 3

    payload["entries"].pop()
    target.write_text(json.dumps(payload))
    with pytest.raises(CheckpointMismatchError):
        AuditChain.verify_export(target)


def test_cli_verify_and_export(tmp_path: Path) -> None:
    db = tmp_path / "janus.db"
    store = JanusStore(db)
    _prediction(store)
    store.close()

    runner = CliRunner()
    verify = runner.invoke(app, ["audit", "verify", "--db", str(db)])
    assert verify.exit_code == 0, verify.output
    assert "audit chain OK" in verify.output

    out = tmp_path / "audit.json"
    export = runner.invoke(app, ["audit", "export", "--out", str(out), "--db", str(db)])
    assert export.exit_code == 0, export.output
    assert out.exists()

    broken = runner.invoke(
        app, ["audit", "verify", "--db", str(db), "--checkpoint", str(out)]
    )
    assert broken.exit_code == 0, broken.output


def test_unknown_kind_is_rejected() -> None:
    chain = AuditChain(JanusStore(":memory:"))
    with pytest.raises(ValueError):
        chain.append("advice", "x", {})
    assert issubclass(ChainGapError, AuditError)


def test_rewritten_settlement_pointer_is_detected() -> None:
    store = JanusStore(":memory:")
    ledger, prediction = _prediction(store)
    ledger.settle(
        prediction.id,
        realized_value={"direction": "up"},
        source="test",
        realized_at=T0 + timedelta(days=30),
    )
    store.connection.execute(
        "UPDATE prediction SET outcome_id = 'not-the-outcome' WHERE id = ?",
        (prediction.id,),
    )
    store.connection.commit()

    with pytest.raises(SourceDriftError):
        AuditChain(store).verify()
