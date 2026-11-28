"""Encryption at rest: envelope keys, field encryption, rotation, migration."""

from __future__ import annotations

import base64
import json
import os
import sqlite3
import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from janus.cli import app
from janus.data.blob import EncryptedBlobStore, LocalBlobStore
from janus.memory.encryption import (
    CiphertextInvalidError,
    EncryptionRequiredError,
    KeyConfigError,
    KeyInUseError,
    KeyMismatchError,
    KeyMissingError,
    PlaintextBlobError,
    load_master_key,
)
from janus.memory.encryption_service import (
    begin_rotation,
    migrate,
    retire,
    rotate,
    status,
)
from janus.memory.models import Observation, ObservationKind, Outcome, Prediction, Thesis, ThesisStatus
from janus.memory.store import JanusStore, open_store

MASTER = b"m" * 32
OTHER_MASTER = b"x" * 32
MASTER_B64 = base64.b64encode(MASTER).decode("ascii")
MARKER = "ACME-FREE-TEXT-MARKER-155"
NOW = datetime(2026, 1, 15, tzinfo=timezone.utc)


def _seeded_store(db: Path, master: bytes = MASTER) -> JanusStore:
    store = JanusStore(db, master_key=master)
    store.insert_thesis(
        Thesis(
            id="t1",
            entity_id="ACME",
            persona_id=None,
            horizon="3M",
            statement=f"{MARKER} thesis statement",
            assumptions=["assumption-marker"],
            catalysts=["catalyst-marker"],
            risks=["risk-marker"],
            falsifiers=["falsifier-marker"],
            status=ThesisStatus.active,
            created_at=NOW,
            as_of=NOW,
        )
    )
    store.insert_prediction(
        Prediction(
            id="p1",
            thesis_id="t1",
            target=f"{MARKER} price target",
            horizon="3M",
            probability=0.6,
            quantiles={"p50": 1.0},
            model_version="m1",
            features_hash="abc",
            created_at=NOW,
            as_of=NOW,
        )
    )
    store.insert_outcome(
        Outcome(
            id="o1",
            prediction_id="p1",
            realized_value={"marker": MARKER},
            realized_at=NOW,
            source="manual",
            score=0.1,
        )
    )
    return store


def test_master_key_loading_is_strict(tmp_path: Path) -> None:
    assert load_master_key({"JANUS_MASTER_KEY": MASTER_B64}) == MASTER

    key_file = tmp_path / "master.key"
    key_file.write_text(MASTER_B64 + "\n", encoding="utf-8")
    os.chmod(key_file, 0o600)
    assert load_master_key({"JANUS_MASTER_KEY_FILE": str(key_file)}) == MASTER

    os.chmod(key_file, 0o644)
    with pytest.raises(KeyConfigError) as excinfo:
        load_master_key({"JANUS_MASTER_KEY_FILE": str(key_file)})
    assert excinfo.value.code == "key_invalid"
    assert "permission" in str(excinfo.value)

    with pytest.raises(KeyMissingError) as excinfo:
        load_master_key({})
    assert excinfo.value.code == "key_missing"
    assert MASTER_B64 not in str(excinfo.value)


def test_envelope_stores_wrapped_deks_only(tmp_path: Path) -> None:
    store = _seeded_store(tmp_path / "janus.db")
    manager = store.key_manager
    assert manager is not None
    assert manager.active_key_id == "k1"
    dek = manager.dek("k1")
    row = store.connection.execute(
        "SELECT wrapped_dek, state FROM encryption_key WHERE key_id = 'k1'"
    ).fetchone()
    wrapped, state = str(row[0]), str(row[1])
    assert state == "active"
    assert wrapped.startswith("januswrap1.")
    assert base64.urlsafe_b64encode(dek).decode().rstrip("=") not in wrapped
    assert dek not in wrapped.encode()
    store.close()


def test_fields_are_sealed_and_readable(tmp_path: Path) -> None:
    db = tmp_path / "janus.db"
    store = _seeded_store(db)
    thesis = store.get_thesis("t1")
    prediction = store.get_prediction("p1")
    outcome = store.get_outcome("o1")
    assert thesis is not None and prediction is not None and outcome is not None
    assert thesis.statement == f"{MARKER} thesis statement"
    assert thesis.assumptions == ["assumption-marker"]
    assert prediction.target == f"{MARKER} price target"
    assert outcome.realized_value == {"marker": MARKER}

    row = store.connection.execute(
        "SELECT statement, assumptions, key_id FROM thesis WHERE id = 't1'"
    ).fetchone()
    assert str(row["key_id"]) == "k1"
    assert str(row["statement"]).startswith("janus1.k1.")
    assert MARKER not in str(row["statement"])
    assert MARKER not in str(row["assumptions"])
    store.close()


def test_at_rest_markers_absent_from_dump_and_bytes(tmp_path: Path) -> None:
    db = tmp_path / "janus.db"
    store = _seeded_store(db)
    store.close()

    dump = "\n".join(sqlite3.connect(db).iterdump())
    assert MARKER not in dump
    assert MARKER not in db.read_bytes().decode("latin-1")


def test_context_swap_tamper_and_unknown_key_fail_closed(tmp_path: Path) -> None:
    store = _seeded_store(tmp_path / "janus.db")
    sealer = store.sealer
    assert sealer is not None
    token = sealer.seal(b"value", context="thesis.statement:t1")
    assert sealer.unseal(token, context="thesis.statement:t1") == b"value"

    with pytest.raises(CiphertextInvalidError) as excinfo:
        sealer.unseal(token, context="thesis.risks:t1")
    assert excinfo.value.code == "ciphertext_invalid"

    parts = token.split(".")
    raw = bytearray(base64.urlsafe_b64decode(parts[3] + "=="))
    raw[0] ^= 0xFF
    tampered = ".".join(
        [parts[0], parts[1], parts[2], base64.urlsafe_b64encode(bytes(raw)).decode().rstrip("=")]
    )
    with pytest.raises(CiphertextInvalidError):
        sealer.unseal(tampered, context="thesis.statement:t1")

    unknown = ".".join(["janus1", "k9", parts[2], parts[3]])
    with pytest.raises(KeyMismatchError) as excinfo:
        sealer.unseal(unknown, context="thesis.statement:t1")
    assert excinfo.value.code == "key_mismatch"
    store.close()


def test_store_fails_closed_without_or_with_wrong_key(tmp_path: Path) -> None:
    db = tmp_path / "janus.db"
    _seeded_store(db).close()

    with pytest.raises(KeyMissingError) as excinfo:
        JanusStore(db)
    assert excinfo.value.code == "key_missing"

    with pytest.raises(KeyMismatchError) as excinfo:
        JanusStore(db, master_key=OTHER_MASTER)
    assert excinfo.value.code == "key_mismatch"


def test_plaintext_store_stays_backward_compatible(tmp_path: Path) -> None:
    db = tmp_path / "legacy.db"
    store = JanusStore(db)
    assert not store.encryption_enabled
    store.insert_thesis(
        Thesis(
            id="t0",
            entity_id="ACME",
            persona_id=None,
            horizon="1M",
            statement="legacy plaintext",
            assumptions=[],
            catalysts=[],
            risks=[],
            falsifiers=[],
            status=ThesisStatus.active,
            created_at=NOW,
            as_of=NOW,
        )
    )
    assert store.get_thesis("t0").statement == "legacy plaintext"
    store.close()


def test_migration_is_idempotent_with_backup(tmp_path: Path) -> None:
    db = tmp_path / "legacy.db"
    plain = JanusStore(db)
    plain.insert_thesis(
        Thesis(
            id="t1",
            entity_id="ACME",
            persona_id=None,
            horizon="1M",
            statement=f"{MARKER} plaintext",
            assumptions=["a"],
            catalysts=[],
            risks=[],
            falsifiers=[],
            status=ThesisStatus.active,
            created_at=NOW,
            as_of=NOW,
        )
    )
    plain.close()
    assert MARKER in db.read_bytes().decode("latin-1")

    store = JanusStore(db, master_key=MASTER)
    first = migrate(store)
    assert first["rows_encrypted"] == 1
    assert Path(first["backup"]).exists()
    assert stat.S_IMODE(Path(first["backup"]).stat().st_mode) == 0o600
    assert store.get_thesis("t1").statement == f"{MARKER} plaintext"

    second = migrate(store)
    assert second["rows_encrypted"] == 0
    assert store.get_thesis("t1").statement == f"{MARKER} plaintext"
    store.close()


def test_migration_failure_restores_backup(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "legacy.db"
    plain = JanusStore(db)
    plain.insert_thesis(
        Thesis(
            id="t1",
            entity_id="ACME",
            persona_id=None,
            horizon="1M",
            statement=f"{MARKER} plaintext",
            assumptions=[],
            catalysts=[],
            risks=[],
            falsifiers=[],
            status=ThesisStatus.active,
            created_at=NOW,
            as_of=NOW,
        )
    )
    plain.close()

    store = JanusStore(db, master_key=MASTER)
    sealer = store.sealer
    assert sealer is not None

    def boom(*args, **kwargs):
        raise RuntimeError("injected crypto failure")

    monkeypatch.setattr(sealer, "seal", boom)
    with pytest.raises(RuntimeError):
        migrate(store)
    monkeypatch.undo()

    # The backup was restored, so the row is plaintext again and still readable.
    row = store.connection.execute("SELECT statement, key_id FROM thesis WHERE id = 't1'").fetchone()
    assert row["key_id"] is None
    assert row["statement"] == f"{MARKER} plaintext"
    assert store.get_thesis("t1").statement == f"{MARKER} plaintext"
    store.close()


def test_rotation_rekeys_and_keeps_old_key_until_retired(tmp_path: Path) -> None:
    db = tmp_path / "janus.db"
    store = _seeded_store(db)

    with pytest.raises(KeyInUseError) as excinfo:
        retire(store, "k1", assume_no_blobs=True)
    assert excinfo.value.code == "key_in_use"

    report = rotate(store)
    assert report["key_id"] == "k2"
    assert report["rows_rotated"] == 3
    assert store.get_thesis("t1").statement == f"{MARKER} thesis statement"
    assert store.get_prediction("p1").target == f"{MARKER} price target"
    assert store.get_outcome("o1").realized_value == {"marker": MARKER}

    keys = {key.key_id: key.state for key in store.key_manager.keys()}
    assert keys == {"k1": "retired", "k2": "active"}
    state = status(store)
    assert state["active_key_id"] == "k2"
    assert state["rows"]["thesis"] == {"k2": 1}
    assert state["plaintext_rows"] == 0

    retire(store, "k1", assume_no_blobs=True)
    assert [key.key_id for key in store.key_manager.keys()] == ["k2"]
    store.close()


def test_rotation_resumes_after_partial_run(tmp_path: Path) -> None:
    store = _seeded_store(tmp_path / "janus.db")
    first = rotate(store, batch_size=1, tables=["thesis"])
    assert first["key_id"] == "k2"
    pending = [row["table"] for row in status(store)["rotation"]]
    assert pending == ["outcome", "prediction"]

    second = rotate(store, batch_size=1)
    assert second["key_id"] == "k2"
    assert store.key_manager.active_key_id == "k2"
    assert status(store)["rows"] == {
        "thesis": {"k2": 1},
        "prediction": {"k2": 1},
        "outcome": {"k2": 1},
    }
    assert status(store)["rotation"] == []
    store.close()


def test_rotation_requires_migration_first(tmp_path: Path) -> None:
    db = tmp_path / "legacy.db"
    plain = JanusStore(db)
    plain.insert_thesis(
        Thesis(
            id="t1",
            entity_id="ACME",
            persona_id=None,
            horizon="1M",
            statement="plaintext",
            assumptions=[],
            catalysts=[],
            risks=[],
            falsifiers=[],
            status=ThesisStatus.active,
            created_at=NOW,
            as_of=NOW,
        )
    )
    plain.close()

    store = JanusStore(db, master_key=MASTER)
    with pytest.raises(EncryptionRequiredError):
        begin_rotation(store)
    store.close()


def test_blob_store_uses_the_same_keys(tmp_path: Path) -> None:
    store = _seeded_store(tmp_path / "janus.db")
    sealer = store.sealer
    assert sealer is not None
    blobs = EncryptedBlobStore(tmp_path / "blobs", sealer)
    digest = blobs.put(b"licensed transcript")
    assert b"licensed transcript" not in blobs.path(digest).read_bytes()
    assert blobs.get(digest) == b"licensed transcript"

    legacy = LocalBlobStore(tmp_path / "legacy-blobs")
    legacy_digest = legacy.put(b"old payload")
    old = EncryptedBlobStore(tmp_path / "legacy-blobs", sealer)
    with pytest.raises(PlaintextBlobError):
        old.get(legacy_digest)
    assert old.migrate_plaintext() == 1
    assert old.get(legacy_digest) == b"old payload"

    rotate(store, blob_root=tmp_path / "blobs")
    assert blobs.get(digest) == b"licensed transcript"
    assert blobs.status().by_key_id == {"k2": 1}
    store.close()


def test_cli_init_status_migrate_rotate_and_fail_closed(tmp_path: Path) -> None:
    db = tmp_path / "janus.db"
    runner = CliRunner()
    env = {"JANUS_MASTER_KEY": MASTER_B64}

    result = runner.invoke(app, ["keys", "init", "--db", str(db), "--json"], env=env)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["active_key_id"] == "k1"

    result = runner.invoke(app, ["keys", "status", "--db", str(db), "--json"], env=env)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["active_key_id"] == "k1"

    result = runner.invoke(app, ["keys", "rotate", "--db", str(db), "--batch-size", "1"], env=env)
    assert result.exit_code == 0, result.output
    assert "k2" in result.output

    result = runner.invoke(app, ["keys", "status", "--db", str(db)], env={})
    assert result.exit_code == 1
    combined = result.output + getattr(result, "stderr", "")
    assert "key_missing" in combined
    assert MASTER_B64 not in combined


def test_config_show_does_not_leak_the_master_key() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["config", "show"], env={"JANUS_MASTER_KEY": MASTER_B64})
    combined = result.output + getattr(result, "stderr", "")
    assert MASTER_B64 not in combined
    assert "JANUS_MASTER_KEY" not in combined


def test_as_of_queries_keep_plaintext_ordering(tmp_path: Path) -> None:
    store = _seeded_store(tmp_path / "janus.db")
    store.insert_observation(
        Observation(
            id="obs1",
            entity_id="ACME",
            kind=ObservationKind.price,
            source="test",
            published_at=NOW,
            observed_at=NOW,
            valid_from=None,
            valid_to=None,
            value={"close": 10.0},
            unit="USD",
            confidence=1.0,
            raw_hash="h1",
            raw_uri=None,
            snapshot_id=None,
        )
    )
    rows = store.query_observations_as_of("ACME", NOW, mode="observed")
    assert [row.id for row in rows] == ["obs1"]
    assert rows[0].value == {"close": 10.0}
    store.close()


def test_audit_chain_seals_prediction_and_outcome_payloads(tmp_path: Path) -> None:
    from janus.forecast.ledger import PredictionLedger
    from janus.memory.audit import AuditChain, SourceDriftError

    db = tmp_path / "janus.db"
    store = JanusStore(db, master_key=MASTER)
    ledger = PredictionLedger(store)
    prediction = ledger.record(
        thesis_id="t1",
        target=f"{MARKER} audited target",
        horizon="1M",
        as_of=NOW,
        model_version="m1",
        features_hash="h1",
    )
    outcome = ledger.settle(
        prediction.id,
        realized_value={"marker": MARKER},
        source="manual",
        realized_at=NOW,
    )
    assert outcome.prediction_id == prediction.id

    # The chain verifies (sealed payloads are unsealed for the live comparison).
    report = AuditChain(store).verify()
    assert report.count == 2

    payloads = [
        str(row[0])
        for row in store.connection.execute("SELECT payload FROM audit_entry").fetchall()
    ]
    assert payloads and all(MARKER not in payload for payload in payloads)
    store.close()

    dump = "\n".join(sqlite3.connect(db).iterdump())
    assert MARKER not in dump
    assert MARKER not in db.read_bytes().decode("latin-1")

    # Drift detection still works after sealing.
    store = JanusStore(db, master_key=MASTER)
    sealer = store.sealer
    assert sealer is not None
    tampered = sealer.seal(b"tampered", context=f"prediction.target:{prediction.id}")
    store.connection.execute(
        "UPDATE prediction SET target = ? WHERE id = ?", (tampered, prediction.id)
    )
    store.connection.commit()
    with pytest.raises(SourceDriftError):
        AuditChain(store).verify()
    store.close()


def test_migration_scrubs_live_db_but_backup_keeps_plaintext(tmp_path: Path) -> None:
    db = tmp_path / "legacy.db"
    plain = JanusStore(db)
    plain.insert_thesis(
        Thesis(
            id="t1",
            entity_id="ACME",
            persona_id=None,
            horizon="1M",
            statement=f"{MARKER} plaintext",
            assumptions=[],
            catalysts=[],
            risks=[],
            falsifiers=[],
            status=ThesisStatus.active,
            created_at=NOW,
            as_of=NOW,
        )
    )
    plain.close()

    store = JanusStore(db, master_key=MASTER)
    result = migrate(store)
    assert result["rows_encrypted"] == 1
    store.close()

    # secure_delete + VACUUM scrub the live file; the backup is plaintext.
    assert MARKER not in db.read_bytes().decode("latin-1")
    backup = Path(result["backup"])
    assert MARKER in backup.read_bytes().decode("latin-1")


def test_migration_can_shred_its_plaintext_backup(tmp_path: Path) -> None:
    db = tmp_path / "legacy.db"
    plain = JanusStore(db)
    plain.insert_thesis(
        Thesis(
            id="t1",
            entity_id="ACME",
            persona_id=None,
            horizon="1M",
            statement=f"{MARKER} plaintext",
            assumptions=[],
            catalysts=[],
            risks=[],
            falsifiers=[],
            status=ThesisStatus.active,
            created_at=NOW,
            as_of=NOW,
        )
    )
    plain.close()

    store = JanusStore(db, master_key=MASTER)
    result = migrate(store, shred_backup=True)
    store.close()
    assert result["backup"] is None
    assert not list(tmp_path.glob("*.bak"))


def test_retire_refuses_when_blobs_still_use_the_key(tmp_path: Path) -> None:
    store = _seeded_store(tmp_path / "janus.db")
    sealer = store.sealer
    assert sealer is not None
    blobs = EncryptedBlobStore(tmp_path / "blobs", sealer)
    blobs.put(b"blob payload")
    rotate(store)  # rows move to k2; the blob is still k1

    with pytest.raises(KeyInUseError):
        retire(store, "k1")  # must not delete a key that may seal blobs
    with pytest.raises(KeyInUseError):
        retire(store, "k1", blob_root=tmp_path / "blobs")

    blobs.rotate()
    retire(store, "k1", blob_root=tmp_path / "blobs")
    assert [key.key_id for key in store.key_manager.keys()] == ["k2"]
    assert blobs.get(blobs.iter_digests()[0]) == b"blob payload"
    store.close()


def test_key_material_cache_and_wrap_aad_binding(tmp_path: Path) -> None:
    store = _seeded_store(tmp_path / "janus.db")
    manager = store.key_manager
    assert manager is not None
    first = manager.dek("k1")
    assert manager.dek("k1") is first
    assert "k1" in manager._dek_cache

    # Swapping wrapped DEKs between key ids must fail authentication.
    rotate(store)
    rows = store.connection.execute(
        "SELECT key_id, wrapped_dek FROM encryption_key ORDER BY key_id"
    ).fetchall()
    wrapped = {str(row[0]): str(row[1]) for row in rows}
    store.connection.execute(
        "UPDATE encryption_key SET wrapped_dek = ? WHERE key_id = 'k1'",
        (wrapped["k2"],),
    )
    store.connection.execute(
        "UPDATE encryption_key SET wrapped_dek = ? WHERE key_id = 'k2'",
        (wrapped["k1"],),
    )
    store.connection.commit()
    from janus.memory.encryption import KeyManager

    swapped = KeyManager(store.connection, MASTER)
    with pytest.raises(KeyMismatchError):
        swapped.dek("k1")
    store.close()


def test_blob_put_seals_a_preexisting_plaintext_blob(tmp_path: Path) -> None:
    payload = b"legacy bytes"
    legacy = LocalBlobStore(tmp_path / "blobs")
    digest = legacy.put(payload)
    assert legacy.get(digest) == payload

    store = _seeded_store(tmp_path / "janus.db")
    sealer = store.sealer
    assert sealer is not None
    blobs = EncryptedBlobStore(tmp_path / "blobs", sealer)
    assert blobs.put(payload) == digest
    assert b"legacy bytes" not in blobs.path(digest).read_bytes()
    assert blobs.get(digest) == payload
    store.close()


def test_key_ids_cannot_contain_the_envelope_separator(tmp_path: Path) -> None:
    store = _seeded_store(tmp_path / "janus.db")
    sealer = store.sealer
    assert sealer is not None
    parts = sealer.seal(b"x").split(".")
    dotted = ".".join([parts[0], "k.1", parts[2], parts[3]])
    # A key id containing "." cannot be represented in the dot-delimited
    # envelope, so it is rejected rather than parsed as a different key.
    assert not sealer.is_sealed(dotted)
    with pytest.raises(CiphertextInvalidError):
        sealer.unseal(dotted)
    store.close()


def test_cli_reads_an_encrypted_store_with_only_the_env_key(tmp_path: Path) -> None:
    db = tmp_path / "janus.db"
    runner = CliRunner()
    env = {"JANUS_MASTER_KEY": MASTER_B64}

    result = runner.invoke(app, ["keys", "init", "--db", str(db)], env=env)
    assert result.exit_code == 0, result.output

    # A normal command, not `janus keys`, must open the encrypted store.
    ok = runner.invoke(app, ["brief", "ACME", "--db", str(db)], env=env)
    assert ok.exit_code == 0, ok.output + getattr(ok, "stderr", "")

    bad = runner.invoke(
        app, ["brief", "ACME", "--db", str(db)], env={"JANUS_MASTER_KEY": ""}
    )
    assert bad.exit_code == 1
    combined = bad.output + getattr(bad, "stderr", "")
    assert "error [key_missing]" in combined
    assert "Traceback" not in combined


def test_open_store_does_not_turn_a_plaintext_store_into_an_encrypted_one(
    tmp_path: Path,
) -> None:
    db = tmp_path / "plain.db"
    store = open_store(db, environ={"JANUS_MASTER_KEY": MASTER_B64})
    assert not store.encryption_enabled
    count = store.connection.execute("SELECT COUNT(*) FROM encryption_key").fetchone()[0]
    assert int(count) == 0
    store.close()


def test_open_store_reports_a_typed_error_without_the_key(tmp_path: Path) -> None:
    db = tmp_path / "janus.db"
    _seeded_store(db).close()
    with pytest.raises(KeyMissingError) as excinfo:
        open_store(db, environ={})
    assert excinfo.value.code == "key_missing"


def test_retire_refuses_while_audit_payloads_use_the_key(tmp_path: Path) -> None:
    from janus.forecast.ledger import PredictionLedger
    from janus.memory.audit import AuditChain

    db = tmp_path / "janus.db"
    store = JanusStore(db, master_key=MASTER)
    ledger = PredictionLedger(store)
    prediction = ledger.record(
        thesis_id="t1",
        target=f"{MARKER} audited target",
        horizon="1M",
        as_of=NOW,
        model_version="m1",
        features_hash="h1",
    )
    ledger.settle(
        prediction.id,
        realized_value={"marker": MARKER},
        source="manual",
        realized_at=NOW,
    )

    rotate(store)  # rows move to k2; sealed audit payloads stay on k1
    assert AuditChain(store).verify().count == 2
    with pytest.raises(KeyInUseError, match="audit entries"):
        retire(store, "k1", assume_no_blobs=True)
    assert "k1" in {key.key_id for key in store.key_manager.keys()}
    assert AuditChain(store).verify().count == 2
    store.close()
