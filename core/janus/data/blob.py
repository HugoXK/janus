from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from janus.memory.encryption import PlaintextBlobError, Sealer

_DIGEST = re.compile(r"^[0-9a-f]{64}$")


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
    """Content-addressed storage for raw source documents."""

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

    def path(self, digest: str) -> Path:
        return self.root / digest[:2] / digest

    def get(self, digest: str) -> bytes:
        return self.path(digest).read_bytes()


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
            return digest
        sealed = self.sealer.seal(data, context=self._context(digest)).encode("ascii")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write(path, sealed)
        return digest

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

    def is_sealed(self, digest: str) -> bool:
        return self.sealer.is_sealed(self.path(digest).read_bytes())

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
    "EncryptedBlobStore",
    "LocalBlobStore",
    "RotationReport",
]
