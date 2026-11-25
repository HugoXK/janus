from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, List, Optional
from uuid import uuid4

from ..memory.models import utcnow
from ..memory.store import JanusStore
from .signing import ShareSigner, payload_hash

DISCLAIMER = "Janus is research tooling, not investment advice."


def _normalize_as_of(value: datetime | str) -> str:
    stamp = value if isinstance(value, datetime) else datetime.fromisoformat(
        str(value).replace("Z", "+00:00")
    )
    if stamp.tzinfo is None or stamp.tzinfo.utcoffset(stamp) is None:
        raise ValueError("as_of must be timezone-aware")
    return stamp.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True)
class ApprovalCard:
    request_id: str
    kind: str
    title: str
    as_of: str
    snapshot_hash: str
    payload_hash: str
    requested_by: str
    status: str
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ShareRequest:
    id: str
    kind: str
    created_at: str
    as_of: str
    snapshot_hash: str
    payload: dict[str, Any]
    status: str
    requested_by: str
    approved_by: Optional[str]
    approved_at: Optional[str]
    envelope: Optional[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def card(self) -> ApprovalCard:
        return ApprovalCard(
            request_id=self.id,
            kind=self.kind,
            title=f"Share {self.kind}",
            as_of=self.as_of,
            snapshot_hash=self.snapshot_hash,
            payload_hash=payload_hash(self.payload),
            requested_by=self.requested_by,
            status=self.status,
            warnings=(DISCLAIMER, "The payload will be signed at approval time."),
        )


class ShareService:
    """Approval-first sharing with an append-only audit trail.

    A share request exists in ``pending`` until an explicit approval signs the
    envelope. Rejections and approvals both write audit rows.
    """

    def __init__(self, store: JanusStore, signer: Optional[ShareSigner] = None) -> None:
        self.store = store
        self.signer = signer

    def request(
        self,
        *,
        kind: str,
        payload: dict[str, Any],
        as_of: datetime | str,
        snapshot_hash: str,
        requested_by: str = "local",
    ) -> ShareRequest:
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        if not kind:
            raise ValueError("kind must not be empty")
        if not snapshot_hash:
            raise ValueError("snapshot_hash must not be empty")
        request_id = uuid4().hex
        created_at = utcnow().isoformat()
        row = {
            "id": request_id,
            "kind": str(kind),
            "created_at": created_at,
            "as_of": _normalize_as_of(as_of),
            "snapshot_hash": str(snapshot_hash),
            "payload": payload,
            "status": "pending",
            "requested_by": requested_by,
        }
        self.store.connection.execute(
            """
            INSERT INTO share_request
            (id, kind, created_at, as_of, snapshot_hash, payload, status,
             requested_by, approved_by, approved_at, envelope)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL)
            """,
            (
                row["id"],
                row["kind"],
                row["created_at"],
                row["as_of"],
                row["snapshot_hash"],
                json.dumps(row["payload"], sort_keys=True, default=str),
                row["status"],
                row["requested_by"],
            ),
        )
        self._audit(
            request_id,
            action="requested",
            actor=requested_by,
            detail={"kind": row["kind"], "payload_hash": payload_hash(payload)},
        )
        self.store.connection.commit()
        return self.get(request_id)

    def get(self, request_id: str) -> ShareRequest:
        row = self.store.connection.execute(
            "SELECT * FROM share_request WHERE id = ?", (request_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown share request: {request_id}")
        return self._row_to_request(row)

    def list(self, status: Optional[str] = None) -> list[ShareRequest]:
        if status is None:
            rows = self.store.connection.execute(
                "SELECT * FROM share_request ORDER BY created_at DESC"
            ).fetchall()
        else:
            rows = self.store.connection.execute(
                "SELECT * FROM share_request WHERE status = ? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        return [self._row_to_request(row) for row in rows]

    def approve(
        self,
        request_id: str,
        *,
        approver: str,
        signer: Optional[ShareSigner] = None,
    ) -> ShareRequest:
        signer = signer or self.signer
        if signer is None:
            raise ValueError("a share signer is required for approval")
        request = self.get(request_id)
        if request.status == "approved":
            return request
        if request.status == "rejected":
            raise ValueError(f"share request was rejected: {request_id}")
        envelope = signer.build_envelope(
            kind=request.kind,
            payload=request.payload,
            as_of=request.as_of,
            snapshot_hash=request.snapshot_hash,
        )
        approved_at = utcnow().isoformat()
        self.store.connection.execute(
            """
            UPDATE share_request
            SET status = 'approved', approved_by = ?, approved_at = ?, envelope = ?
            WHERE id = ?
            """,
            (approver, approved_at, json.dumps(envelope, sort_keys=True, default=str), request_id),
        )
        self._audit(
            request_id,
            action="approved",
            actor=approver,
            detail={"payload_hash": payload_hash(request.payload)},
        )
        self.store.connection.commit()
        return self.get(request_id)

    def reject(self, request_id: str, *, approver: str, reason: str = "") -> ShareRequest:
        request = self.get(request_id)
        if request.status != "pending":
            raise ValueError(f"share request is not pending: {request.status}")
        self.store.connection.execute(
            "UPDATE share_request SET status = 'rejected', approved_by = ?, "
            "approved_at = ? WHERE id = ?",
            (approver, utcnow().isoformat(), request_id),
        )
        self._audit(
            request_id,
            action="rejected",
            actor=approver,
            detail={"reason": reason},
        )
        self.store.connection.commit()
        return self.get(request_id)

    def verify(
        self, envelope: dict[str, Any], *, signer: Optional[ShareSigner] = None
    ) -> bool:
        signer = signer or self.signer
        if signer is None:
            raise ValueError("a share signer is required for verification")
        return signer.verify(envelope)

    def audit_trail(self, request_id: str) -> List[dict[str, Any]]:
        rows = self.store.connection.execute(
            "SELECT action, actor, at, detail FROM share_audit WHERE request_id = ? ORDER BY id",
            (request_id,),
        ).fetchall()
        return [
            {
                "action": row["action"],
                "actor": row["actor"],
                "at": row["at"],
                "detail": json.loads(row["detail"]),
            }
            for row in rows
        ]

    def _audit(
        self, request_id: str, *, action: str, actor: str, detail: dict[str, Any]
    ) -> None:
        self.store.connection.execute(
            """
            INSERT INTO share_audit (request_id, action, actor, at, detail)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                request_id,
                action,
                actor,
                utcnow().isoformat(),
                json.dumps(detail, sort_keys=True, default=str),
            ),
        )

    @staticmethod
    def _row_to_request(row: Any) -> ShareRequest:
        return ShareRequest(
            id=row["id"],
            kind=row["kind"],
            created_at=row["created_at"],
            as_of=row["as_of"],
            snapshot_hash=row["snapshot_hash"],
            payload=json.loads(row["payload"]),
            status=row["status"],
            requested_by=row["requested_by"],
            approved_by=row["approved_by"],
            approved_at=row["approved_at"],
            envelope=json.loads(row["envelope"]) if row["envelope"] else None,
        )
