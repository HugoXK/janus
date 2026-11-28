from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any

SIGNATURE_ALGORITHM = "hmac-sha256"
SHARE_VERSION = "share-v1"


class ShareVerificationError(ValueError):
    """Raised when a share envelope is malformed or unverifiable."""


def canonical_json(payload: Any) -> str:
    # ``allow_nan=False`` keeps the signed bytes valid RFC-8259 JSON: a NaN or
    # Infinity payload raises instead of producing an envelope no other JSON
    # implementation can read.
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    )


def payload_hash(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _parse_time(value: datetime | str) -> datetime:
    stamp = value if isinstance(value, datetime) else datetime.fromisoformat(
        str(value).replace("Z", "+00:00")
    )
    if stamp.tzinfo is None or stamp.tzinfo.utcoffset(stamp) is None:
        raise ValueError("as_of must be timezone-aware")
    return stamp.astimezone(timezone.utc)


class ShareSigner:
    """Sign a share envelope with the local bot-social identity.

    This baseline uses HMAC-SHA256 so the core has no cryptography dependency.
    The secret never enters the envelope or logs. For cross-party sharing,
    swap this for an asymmetric signer while keeping the same envelope shape.
    """

    def __init__(self, secret: str | bytes, *, key_id: str = "local") -> None:
        if isinstance(secret, str):
            secret = secret.encode("utf-8")
        if not secret:
            raise ValueError("share signing secret must not be empty")
        if not key_id:
            raise ValueError("key_id must not be empty")
        self._secret = secret
        self.key_id = key_id

    def build_envelope(
        self,
        *,
        kind: str,
        payload: Any,
        as_of: datetime | str,
        snapshot_hash: str,
        request_id: str,
        approved_by: str,
        approved_at: datetime | str,
    ) -> dict[str, Any]:
        if not kind:
            raise ValueError("kind must not be empty")
        if not snapshot_hash:
            raise ValueError("snapshot_hash must not be empty")
        if not request_id:
            raise ValueError("request_id must not be empty")
        if not approved_by:
            raise ValueError("approved_by must not be empty")
        body = {
            "version": SHARE_VERSION,
            "kind": str(kind),
            "request_id": str(request_id),
            "as_of": _parse_time(as_of).isoformat(),
            "snapshot_hash": str(snapshot_hash),
            "payload_hash": payload_hash(payload),
            "payload": payload,
            "approval": {
                "approved_by": str(approved_by),
                "approved_at": _parse_time(approved_at).isoformat(),
            },
            "identity": {
                "key_id": self.key_id,
                "algorithm": SIGNATURE_ALGORITHM,
            },
        }
        return {**body, "signature": self._sign(body)}

    def sign(self, body: dict[str, Any]) -> dict[str, Any]:
        if "signature" in body:
            raise ValueError("body already contains a signature")
        return {**body, "signature": self._sign(body)}

    def verify(self, envelope: dict[str, Any], *, request_id: str) -> bool:
        """Verify an envelope and bind it to the request it was issued for."""

        if not isinstance(envelope, dict):
            return False
        if envelope.get("version") != SHARE_VERSION:
            return False
        if not request_id or envelope.get("request_id") != request_id:
            return False
        identity = envelope.get("identity")
        if not isinstance(identity, dict):
            return False
        if identity.get("algorithm") != SIGNATURE_ALGORITHM:
            return False
        if identity.get("key_id") != self.key_id:
            return False
        signature = envelope.get("signature")
        if not isinstance(signature, str):
            return False
        body = {key: value for key, value in envelope.items() if key != "signature"}
        expected = self._sign(body)
        if not hmac.compare_digest(signature, expected):
            return False
        return body.get("payload_hash") == payload_hash(body.get("payload"))

    def require_valid(self, envelope: dict[str, Any], *, request_id: str) -> dict[str, Any]:
        if not self.verify(envelope, request_id=request_id):
            raise ShareVerificationError("share signature is invalid or bound to another request")
        return envelope

    def _sign(self, body: dict[str, Any]) -> str:
        return hmac.new(
            self._secret,
            canonical_json(body).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
