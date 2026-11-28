from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator, Optional

from janus.memory.encryption import PlaintextBlobError, Sealer

from ..memory.store import JanusStore

_DIGEST = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class BlobGcResult:
    scanned: int
    kept: int
    deleted: int
    bytes_freed: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class BlobEncryptionStatus:
    """Deterministic summary of the blobs under one root."""

    total: int
    sealed: int
    plaintext: int
    by_key_id: dict[str, int]

    def as_dict(self) -> dict[str, object]:
        return {
            "total": self.total,
            "sealed": self.sealed,
            "plaintext": self.plaintext,
            "by_key_id": dict(sorted(self.by_key_id.items())),
        }


@dataclass(frozen=True)
class RotationReport:
    """Result of re-wrapping every sealed blob under the active key."""

    scanned: int
    rotated: int
    plaintext: int
    by_key_id: dict[str, int]

    def as_dict(self) -> dict[str, object]:
        return {
            "scanned": self.scanned,
            "rotated": self.rotated,
            "plaintext": self.plaintext,
            "by_key_id": dict(sorted(self.by_key_id.items())),
        }


class LocalBlobStore:
    """Content-addressed storage for raw source documents.

    Identical bytes share one file. ``gc`` only deletes blobs that no
    observation references through ``raw_hash``, so deleting one observation
    cannot orphan a blob still used by another.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        path = self.path(digest)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return digest

    def put_json(self, value: Any) -> str:
        canonical = json.dumps(
            value, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
        return self.put(canonical)

    def get(self, digest: str) -> bytes:
        return self.path(digest).read_bytes()

    def get_json(self, digest: str) -> Any:
        return json.loads(self.get(digest).decode("utf-8"))

    def path(self, digest: str) -> Path:
        return self.root / digest[:2] / digest

    def verify(self, digest: str) -> bool:
        path = self.path(digest)
        if not path.exists():
            return False
        return hashlib.sha256(path.read_bytes()).hexdigest() == digest

    def iter_digests(self) -> list[str]:
        return sorted(
            path.name
            for path in self.root.glob("*/*")
            if path.is_file() and len(path.name) == 64
        )

    def metrics(self) -> dict[str, int]:
        digests = self.iter_digests()
        return {
            "blobs": len(digests),
            "bytes": sum(self.path(digest).stat().st_size for digest in digests),
        }

    def referenced_digests(self, store: JanusStore) -> set[str]:
        rows = store.connection.execute(
            "SELECT DISTINCT raw_hash FROM observation WHERE raw_hash IS NOT NULL"
        ).fetchall()
        return {str(row["raw_hash"]) for row in rows if row["raw_hash"]}

    def gc(self, store: JanusStore, *, dry_run: bool = False) -> BlobGcResult:
        referenced = self.referenced_digests(store)
        scanned = kept = deleted = bytes_freed = 0
        for digest in self.iter_digests():
            scanned += 1
            if digest in referenced:
                kept += 1
                continue
            path = self.path(digest)
            size = path.stat().st_size
            deleted += 1
            bytes_freed += size
            if not dry_run:
                path.unlink()
        return BlobGcResult(
            scanned=scanned,
            kept=kept,
            deleted=deleted,
            bytes_freed=bytes_freed,
        )

    def delete(self, digest: str) -> Optional[int]:
        """Delete one blob explicitly and return the bytes removed."""

        path = self.path(digest)
        if not path.exists():
            return None
        size = path.stat().st_size
        path.unlink()
        return size


class EncryptedBlobStore:
    """Seal every blob at rest while keeping content addressing by plaintext.

    The path stays ``<root>/<aa>/<sha256(plaintext)>`` so ``raw_hash`` and
    ``raw_uri`` in the store keep pointing at the same document after encryption
    or rotation. The file contents are ``janus1.<key-id>.<nonce>.<ciphertext>``.

    Reads of legacy plaintext files fail closed with :class:`PlaintextBlobError`
    unless the caller explicitly passes ``allow_plaintext=True``; the supported
    migration is :meth:`migrate_plaintext`.
    """

    def __init__(
        self,
        root: Path,
        sealer: Sealer,
        *,
        allow_plaintext: bool = False,
    ) -> None:
        self.root = Path(root)
        self.sealer = sealer
        self.allow_plaintext = allow_plaintext
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, digest: str) -> Path:
        return self.root / digest[:2] / digest

    def put(self, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        path = self.path(digest)
        if path.exists():
            raw = path.read_bytes()
            if not self.sealer.is_sealed(raw):
                # A legacy plaintext blob with this digest must not stay in
                # clear text just because put() found it already on disk.
                sealed = self.sealer.seal(
                    raw, context=self._context(digest)
                ).encode("ascii")
                self._write(path, sealed)
            return digest
        sealed = self.sealer.seal(data, context=self._context(digest)).encode("ascii")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write(path, sealed)
        return digest

    def put_json(self, value: Any) -> str:
        canonical = json.dumps(
            value, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
        return self.put(canonical)

    def get(self, digest: str) -> bytes:
        raw = self.path(digest).read_bytes()
        if self.sealer.is_sealed(raw):
            return self.sealer.unseal(raw.decode("ascii"), context=self._context(digest))
        if self.allow_plaintext:
            return raw
        raise PlaintextBlobError(
            f"blob {digest[:12]} is not sealed; run 'janus keys migrate' "
            "to encrypt existing blobs before reading them"
        )

    def get_json(self, digest: str) -> Any:
        return json.loads(self.get(digest).decode("utf-8"))

    def is_sealed(self, digest: str) -> bool:
        return self.sealer.is_sealed(self.path(digest).read_bytes())

    def verify(self, digest: str) -> bool:
        """Check the plaintext digest, decrypting a sealed blob when needed."""

        try:
            return hashlib.sha256(self.get(digest)).hexdigest() == digest
        except (OSError, PlaintextBlobError):
            return False

    def iter_digests(self) -> list[str]:
        return [digest for digest, _path in self._iter_blobs()]

    def metrics(self) -> dict[str, int]:
        digests = self.iter_digests()
        return {
            "blobs": len(digests),
            "bytes": sum(self.path(digest).stat().st_size for digest in digests),
        }

    def gc(self, store: JanusStore, *, dry_run: bool = False) -> BlobGcResult:
        """Reuse the plaintext GC: it only looks at digests and references."""

        return LocalBlobStore(self.root).gc(store, dry_run=dry_run)

    def delete(self, digest: str) -> Optional[int]:
        return LocalBlobStore(self.root).delete(digest)

    def status(self) -> BlobEncryptionStatus:
        total = sealed = plaintext = 0
        by_key_id: dict[str, int] = {}
        for _digest, path in self._iter_blobs():
            total += 1
            raw = path.read_bytes()
            if not self.sealer.is_sealed(raw):
                plaintext += 1
                continue
            sealed += 1
            key_id = self.sealer.key_id_of(raw.decode("ascii"))
            by_key_id[key_id] = by_key_id.get(key_id, 0) + 1
        return BlobEncryptionStatus(
            total=total,
            sealed=sealed,
            plaintext=plaintext,
            by_key_id=dict(sorted(by_key_id.items())),
        )

    def migrate_plaintext(self) -> int:
        """Seal legacy plaintext blobs in place and return how many moved."""

        migrated = 0
        for digest, path in self._iter_blobs():
            raw = path.read_bytes()
            if self.sealer.is_sealed(raw):
                continue
            sealed = self.sealer.seal(raw, context=self._context(digest)).encode("ascii")
            self._write(path, sealed)
            migrated += 1
        return migrated

    def rotate(self) -> RotationReport:
        """Re-wrap every sealed blob under the active key."""

        scanned = rotated = plaintext = 0
        by_key_id: dict[str, int] = {}
        for digest, path in self._iter_blobs():
            raw = path.read_bytes()
            if not self.sealer.is_sealed(raw):
                plaintext += 1
                continue
            scanned += 1
            token = raw.decode("ascii")
            key_id = self.sealer.key_id_of(token)
            if key_id != self.sealer.active_key_id:
                token = self.sealer.rotate(token, context=self._context(digest))
                self._write(path, token.encode("ascii"))
                rotated += 1
                key_id = self.sealer.key_id_of(token)
            by_key_id[key_id] = by_key_id.get(key_id, 0) + 1
        return RotationReport(
            scanned=scanned,
            rotated=rotated,
            plaintext=plaintext,
            by_key_id=dict(sorted(by_key_id.items())),
        )

    def _iter_blobs(self) -> Iterator[tuple[str, Path]]:
        for path in sorted(self.root.glob("*/*")):
            if not path.is_file() or not _DIGEST.match(path.name):
                continue
            if path.parent.name != path.name[:2]:
                continue
            yield path.name, path

    def _context(self, digest: str) -> str:
        return f"blob:{digest}"

    @staticmethod
    def _write(path: Path, payload: bytes) -> None:
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            tmp.write_bytes(payload)
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink()


__all__ = [
    "BlobEncryptionStatus",
    "BlobGcResult",
    "EncryptedBlobStore",
    "LocalBlobStore",
    "RotationReport",
]
