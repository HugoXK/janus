from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

from ..memory.store import JanusStore


@dataclass(frozen=True)
class BlobGcResult:
    scanned: int
    kept: int
    deleted: int
    bytes_freed: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


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

    def gc(
        self, store: JanusStore, *, dry_run: bool = False
    ) -> BlobGcResult:
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
