from __future__ import annotations

import hashlib
from pathlib import Path


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
