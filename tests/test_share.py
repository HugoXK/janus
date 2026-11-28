from __future__ import annotations

from datetime import datetime, timezone

import pytest

from janus.memory.store import JanusStore
from janus.share.service import ShareService
from janus.share.signing import ShareSigner, payload_hash


def _service() -> tuple[JanusStore, ShareService, ShareSigner]:
    store = JanusStore(":memory:")
    signer = ShareSigner("test-secret", key_id="bot-social")
    return store, ShareService(store, signer), signer


def _request(service: ShareService):
    return service.request(
        kind="forecast",
        payload={"prediction_id": "p1", "probability": 0.7},
        as_of=datetime(2026, 1, 1, tzinfo=timezone.utc),
        snapshot_hash="snap-abc",
        requested_by="alice",
    )


def test_request_is_pending_and_has_an_approval_card() -> None:
    store, service, _ = _service()
    request = _request(service)

    assert request.status == "pending"
    assert request.envelope is None
    card = request.card()
    assert card.request_id == request.id
    assert card.kind == "forecast"
    assert card.snapshot_hash == "snap-abc"
    assert card.payload_hash == payload_hash(request.payload)
    assert any("not investment advice" in warning for warning in card.warnings)
    assert [row["action"] for row in service.audit_trail(request.id)] == ["requested"]


def test_approval_signs_and_verifies() -> None:
    store, service, signer = _service()
    request = _request(service)
    approved = service.approve(request.id, approver="bob")

    assert approved.status == "approved"
    assert approved.approved_by == "bob"
    assert approved.envelope is not None
    assert signer.verify(approved.envelope, request_id=request.id)
    assert service.verify(approved.envelope, request_id=request.id)
    assert approved.envelope["as_of"].startswith("2026-01-01")
    assert approved.envelope["snapshot_hash"] == "snap-abc"
    assert approved.envelope["identity"]["key_id"] == "bot-social"
    assert [row["action"] for row in service.audit_trail(request.id)] == [
        "requested",
        "approved",
    ]

    assert service.approve(request.id, approver="bob").envelope == approved.envelope
    assert [row["action"] for row in service.audit_trail(request.id)] == [
        "requested",
        "approved",
    ]


def test_approval_requires_a_signer() -> None:
    store = JanusStore(":memory:")
    service = ShareService(store)
    request = _request(service)
    with pytest.raises(ValueError, match="signer"):
        service.approve(request.id, approver="bob")


def test_tampering_or_wrong_identity_fails_verification() -> None:
    _, service, signer = _service()
    request = _request(service)
    envelope = service.approve(request.id, approver="bob").envelope
    assert envelope is not None

    tampered = {**envelope, "payload": {"prediction_id": "p1", "probability": 0.1}}
    assert signer.verify(tampered, request_id=request.id) is False

    assert (
        ShareSigner("different", key_id="bot-social").verify(
            envelope, request_id=request.id
        )
        is False
    )
    assert (
        ShareSigner("test-secret", key_id="other").verify(
            envelope, request_id=request.id
        )
        is False
    )
    assert signer.verify({**envelope, "signature": "0" * 64}, request_id=request.id) is False


def test_rejection_is_audited_and_blocks_approval() -> None:
    _, service, _ = _service()
    request = _request(service)
    rejected = service.reject(request.id, approver="bob", reason="not ready")

    assert rejected.status == "rejected"
    assert rejected.envelope is None
    assert service.audit_trail(request.id)[-1]["detail"] == {"reason": "not ready"}
    with pytest.raises(ValueError, match="rejected"):
        service.approve(request.id, approver="bob")


def test_request_validation_and_missing_request() -> None:
    _, service, _ = _service()
    with pytest.raises(ValueError, match="snapshot_hash"):
        service.request(
            kind="thesis",
            payload={},
            as_of=datetime(2026, 1, 1, tzinfo=timezone.utc),
            snapshot_hash="",
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        service.request(
            kind="thesis",
            payload={},
            as_of=datetime(2026, 1, 1),
            snapshot_hash="snap",
        )
    with pytest.raises(KeyError, match="unknown share request"):
        service.get("missing")
    assert service.list("pending") == []


def test_signer_rejects_empty_secret() -> None:
    with pytest.raises(ValueError, match="secret"):
        ShareSigner("")


def test_envelope_is_bound_to_the_request_and_the_approver() -> None:
    _, service, signer = _service()
    first = _request(service)
    second = service.request(
        kind="forecast",
        payload={"prediction_id": "p1", "probability": 0.7},  # same payload
        as_of=datetime(2026, 1, 1, tzinfo=timezone.utc),
        snapshot_hash="snap-abc",
        requested_by="alice",
    )
    envelope = service.approve(first.id, approver="bob").envelope
    assert envelope is not None
    assert envelope["request_id"] == first.id
    assert envelope["approval"]["approved_by"] == "bob"
    assert envelope["approval"]["approved_at"]

    # The same envelope cannot be replayed onto another request with the same
    # payload, as_of and snapshot hash.
    assert signer.verify(envelope, request_id=second.id) is False
    with pytest.raises(ValueError, match="invalid or bound to another request"):
        signer.require_valid(envelope, request_id=second.id)

    # A second approver cannot silently adopt someone else's approval.
    with pytest.raises(ValueError, match="already approved by 'bob'"):
        service.approve(first.id, approver="mallory")


def test_share_audit_is_append_only() -> None:
    import sqlite3

    store, service, _ = _service()
    request = _request(service)
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        store.connection.execute("UPDATE share_audit SET actor = 'someone-else'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        store.connection.execute("DELETE FROM share_audit")
    assert [row["action"] for row in service.audit_trail(request.id)] == ["requested"]


def test_non_finite_payloads_are_rejected() -> None:
    _, service, _ = _service()
    with pytest.raises(ValueError):
        service.request(
            kind="thesis",
            payload={"value": float("nan")},
            as_of=datetime(2026, 1, 1, tzinfo=timezone.utc),
            snapshot_hash="snap",
        )
