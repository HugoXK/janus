from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Optional


class HttpCache:
    """A tiny file-backed JSON cache for HTTP responses.

    The cache is intentionally boring: one file per URL, a TTL, and no
    cross-process locking. It is enough for a local-first research tool and can
    be replaced by a database-backed cache later.
    """

    def __init__(self, root: Path, ttl_seconds: int = 86400) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_seconds

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.root / f"{digest}.json"

    def get(self, key: str) -> Optional[Any]:
        path = self._path(key)
        if not path.exists():
            return None
        if time.time() - path.stat().st_mtime > self.ttl_seconds:
            return None
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return None

    def set(self, key: str, value: Any) -> None:
        self._path(key).write_text(json.dumps(value, sort_keys=True))
