"""Tamper-evident audit chain for the Janus ledger.

Every recorded prediction, settled outcome, share and override can be appended
to a SHA-256 hash chain. A later verification recomputes the chain and compares
it with the live source rows, so a deleted or rewritten row becomes a typed
error instead of silent history drift.

The chain proves *internal* consistency only. It is not a signature: a process
that can write the SQLite file can also drop the append-only triggers. Export a
checkpoint to an external place (the CLI ``janus audit export``) if truncation
of the newest rows matters.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Union

from .models import Outcome, Prediction, utcnow
from .store import JanusStore

CANONICAL_SEPARATOR = "\x1f"
AUDIT_KINDS = ("prediction", "outcome", "share", "override")


class AuditError(Exception):
    """Base class for audit-chain failures."""


class ChainGapError(AuditError):
    """A sequence number is missing: at least one row was deleted."""

    def __init__(self, expected: int, actual: int) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"audit chain gap: expected seq {expected}, found {actual}"
        )


class EntryHashError(AuditError):
    """A stored entry no longer matches its recomputed hash."""

    def __init__(self, seq: int, detail: str = "entry hash mismatch") -> None:
        self.seq = seq
        super().__init__(f"audit entry {seq}: {detail}")


class SourceDriftError(AuditError):
    """A source row (prediction/outcome) differs from its audited payload."""

    def __init__(self, kind: str, ref_id: str) -> None:
        self.kind = kind
        self.ref_id = ref_id
        super().__init__(
            f"audited {kind} {ref_id} differs from the recorded payload"
        )


class SourceMissingError(AuditError):
    """A source row referenced by the chain no longer exists."""

    def __init__(self, kind: str, ref_id: str) -> None:
        self.kind = kind
        self.ref_id = ref_id
        super().__init__(f"audited {kind} {ref_id} is missing")


class CheckpointMismatchError(AuditError):
    """The chain no longer matches an exported checkpoint (e.g. tail truncation)."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"audit checkpoint mismatch: {detail}")


@dataclass(frozen=True)
class AuditEntry:
    seq: int
    kind: str
    ref_id: str
    recorded_at: datetime
    payload: dict[str, Any]
    prev_hash: str
    entry_hash: str


@dataclass(frozen=True)
class AuditCheckpoint:
    """A hash commitment to a chain prefix."""

    count: int
    head_seq: int
    head_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "head_seq": self.head_seq,
            "head_hash": self.head_hash,
        }


@dataclass(frozen=True)
class AuditReport:
    count: int
    head_seq: int
    head_hash: str


def canonical_json(payload: Mapping[str, Any]) -> str:
    """Deterministic JSON text used as hash input and storage format."""

    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def prediction_payload(prediction: Prediction) -> dict[str, Any]:
    """Immutable fields of a prediction.

    ``outcome_id`` is excluded: settlement is the one allowed mutation and must
    not invalidate an ex-ante forecast record.
    """

    payload = prediction.model_dump(mode="json")
    payload.pop("outcome_id", None)
    return payload


def outcome_payload(outcome: Outcome) -> dict[str, Any]:
    return outcome.model_dump(mode="json")


def _recorded_at_text(value: datetime) -> str:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("recorded_at must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()


class AuditChain:
    """Append-only SHA-256 chain over recorded research events."""

    GENESIS = "0" * 64
    AUDIT_VERSION = 1

    def __init__(self, store: JanusStore) -> None:
        self.store = store

    # ------------------------------------------------------------------
    # Append
    # ------------------------------------------------------------------
    def append(
        self,
        kind: str,
        ref_id: str,
        payload: Mapping[str, Any],
        *,
        recorded_at: Optional[datetime] = None,
    ) -> AuditEntry:
        if kind not in AUDIT_KINDS:
            raise ValueError(f"unsupported audit kind: {kind}")
        stamp = _recorded_at_text(recorded_at or utcnow())
        body = canonical_json(payload)

        with self.store.locked():
            row = self.store.connection.execute(
                "SELECT seq, entry_hash FROM audit_entry ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            seq = 1 if row is None else int(row["seq"]) + 1
            prev_hash = self.GENESIS if row is None else str(row["entry_hash"])
            entry_hash = self._hash(seq, kind, ref_id, stamp, body, prev_hash)
            self.store.connection.execute(
                """
                INSERT INTO audit_entry
                (seq, kind, ref_id, recorded_at, payload, prev_hash, entry_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (seq, kind, ref_id, stamp, body, prev_hash, entry_hash),
            )
            self.store.connection.commit()

        return AuditEntry(
            seq=seq,
            kind=kind,
            ref_id=ref_id,
            recorded_at=datetime.fromisoformat(stamp),
            payload=json.loads(body),
            prev_hash=prev_hash,
            entry_hash=entry_hash,
        )

    def record_share(
        self,
        ref_id: str,
        payload: Mapping[str, Any],
        *,
        recorded_at: Optional[datetime] = None,
    ) -> AuditEntry:
        """Audit a shared bundle at the sharing boundary (JAN-043)."""

        return self.append("share", ref_id, payload, recorded_at=recorded_at)

    def record_override(
        self,
        ref_id: str,
        payload: Mapping[str, Any],
        *,
        recorded_at: Optional[datetime] = None,
    ) -> AuditEntry:
        """Audit a manual override, e.g. an operator decision on a forecast."""

        return self.append("override", ref_id, payload, recorded_at=recorded_at)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------
    def entries(
        self, *, as_of: Optional[datetime] = None
    ) -> list[AuditEntry]:
        sql = "SELECT * FROM audit_entry"
        params: list[object] = []
        if as_of is not None:
            sql += " WHERE recorded_at <= ?"
            params.append(_recorded_at_text(as_of))
        sql += " ORDER BY seq ASC"
        rows = self.store.connection.execute(sql, params).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def checkpoint(self, *, as_of: Optional[datetime] = None) -> AuditCheckpoint:
        entries = self.entries(as_of=as_of)
        if not entries:
            return AuditCheckpoint(count=0, head_seq=0, head_hash=self.GENESIS)
        return AuditCheckpoint(
            count=len(entries),
            head_seq=entries[-1].seq,
            head_hash=entries[-1].entry_hash,
        )

    def head(self) -> AuditCheckpoint:
        return self.checkpoint()

    # ------------------------------------------------------------------
    # Verify
    # ------------------------------------------------------------------
    def verify(self, *, checkpoint: Optional[AuditCheckpoint] = None) -> AuditReport:
        with self.store.locked():
            entries = self.entries()
            expected_seq = 1
            prev_hash = self.GENESIS
            for entry in entries:
                if entry.seq != expected_seq:
                    raise ChainGapError(expected_seq, entry.seq)
                recomputed = self._hash(
                    entry.seq,
                    entry.kind,
                    entry.ref_id,
                    entry.recorded_at.isoformat(),
                    canonical_json(entry.payload),
                    entry.prev_hash,
                )
                if recomputed != entry.entry_hash:
                    raise EntryHashError(entry.seq)
                if entry.prev_hash != prev_hash:
                    raise EntryHashError(entry.seq, "previous hash does not link")
                self._check_source(entry)
                prev_hash = entry.entry_hash
                expected_seq += 1

        if checkpoint is not None:
            self._check_checkpoint(entries, checkpoint)

        head = entries[-1] if entries else None
        return AuditReport(
            count=len(entries),
            head_seq=head.seq if head is not None else 0,
            head_hash=head.entry_hash if head is not None else self.GENESIS,
        )

    def _check_source(self, entry: AuditEntry) -> None:
        if entry.kind == "prediction":
            prediction = self.store.get_prediction(entry.ref_id)
            if prediction is None:
                raise SourceMissingError(entry.kind, entry.ref_id)
            current = prediction_payload(prediction)
        elif entry.kind == "outcome":
            outcome = self.store.get_outcome(entry.ref_id)
            if outcome is None:
                raise SourceMissingError(entry.kind, entry.ref_id)
            prediction = self.store.get_prediction(outcome.prediction_id)
            if prediction is None or prediction.outcome_id != outcome.id:
                raise SourceDriftError(entry.kind, entry.ref_id)
            current = outcome_payload(outcome)
        else:
            # Shares and overrides are audited payloads; no live source table
            # exists yet, so the chain itself is the record.
            return
        if canonical_json(current) != canonical_json(entry.payload):
            raise SourceDriftError(entry.kind, entry.ref_id)

    def _check_checkpoint(
        self, entries: list[AuditEntry], checkpoint: AuditCheckpoint
    ) -> None:
        if checkpoint.head_seq == 0:
            if entries:
                raise CheckpointMismatchError("checkpoint is empty but the chain is not")
            return
        if len(entries) < checkpoint.head_seq:
            raise CheckpointMismatchError(
                f"chain has {len(entries)} entries, checkpoint committed {checkpoint.head_seq}"
            )
        actual = entries[checkpoint.head_seq - 1].entry_hash
        if actual != checkpoint.head_hash:
            raise CheckpointMismatchError(
                f"head hash at seq {checkpoint.head_seq} does not match"
            )
        if checkpoint.count != checkpoint.head_seq:
            raise CheckpointMismatchError("count does not match head_seq")

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def export(
        self,
        path: Union[str, Path],
        *,
        as_of: Optional[datetime] = None,
    ) -> AuditCheckpoint:
        entries = self.entries(as_of=as_of)
        checkpoint = self.checkpoint(as_of=as_of)
        payload = {
            "version": self.AUDIT_VERSION,
            "as_of": _recorded_at_text(as_of) if as_of is not None else None,
            "checkpoint": checkpoint.as_dict(),
            "entries": [
                {
                    "seq": entry.seq,
                    "kind": entry.kind,
                    "ref_id": entry.ref_id,
                    "recorded_at": entry.recorded_at.isoformat(),
                    "payload": entry.payload,
                    "prev_hash": entry.prev_hash,
                    "entry_hash": entry.entry_hash,
                }
                for entry in entries
            ],
        }
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        return checkpoint

    @classmethod
    def verify_export(cls, path: Union[str, Path]) -> AuditReport:
        """Verify an exported chain file without a live store."""

        data = json.loads(Path(path).read_text())
        if data.get("version") != cls.AUDIT_VERSION:
            raise AuditError(f"unsupported audit export version: {data.get('version')}")
        entries = data.get("entries") or []
        prev_hash = cls.GENESIS
        expected_seq = 1
        for entry in entries:
            if entry["seq"] != expected_seq:
                raise ChainGapError(expected_seq, entry["seq"])
            recomputed = cls._hash(
                entry["seq"],
                entry["kind"],
                entry["ref_id"],
                entry["recorded_at"],
                canonical_json(entry["payload"]),
                entry["prev_hash"],
            )
            if recomputed != entry["entry_hash"]:
                raise EntryHashError(entry["seq"])
            if entry["prev_hash"] != prev_hash:
                raise EntryHashError(entry["seq"], "previous hash does not link")
            prev_hash = entry["entry_hash"]
            expected_seq += 1

        stored = data.get("checkpoint") or {}
        actual: dict[str, Any] = {
            "count": len(entries),
            "head_seq": entries[-1]["seq"] if entries else 0,
            "head_hash": entries[-1]["entry_hash"] if entries else cls.GENESIS,
        }
        if stored != actual:
            raise CheckpointMismatchError("exported checkpoint does not match its entries")
        return AuditReport(
            count=int(actual["count"]),
            head_seq=int(actual["head_seq"]),
            head_hash=str(actual["head_hash"]),
        )

    @classmethod
    def checkpoint_from_file(cls, path: Union[str, Path]) -> AuditCheckpoint:
        data = json.loads(Path(path).read_text())
        raw = data.get("checkpoint", data)
        return AuditCheckpoint(
            count=int(raw["count"]),
            head_seq=int(raw["head_seq"]),
            head_hash=str(raw["head_hash"]),
        )

    # ------------------------------------------------------------------
    # Hashing helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _hash(
        seq: int,
        kind: str,
        ref_id: str,
        recorded_at: str,
        payload_text: str,
        prev_hash: str,
    ) -> str:
        material = CANONICAL_SEPARATOR.join(
            [str(seq), kind, ref_id, recorded_at, prev_hash, payload_text]
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    @staticmethod
    def _row_to_entry(row: Any) -> AuditEntry:
        return AuditEntry(
            seq=int(row["seq"]),
            kind=str(row["kind"]),
            ref_id=str(row["ref_id"]),
            recorded_at=datetime.fromisoformat(str(row["recorded_at"])),
            payload=json.loads(row["payload"]),
            prev_hash=str(row["prev_hash"]),
            entry_hash=str(row["entry_hash"]),
        )
