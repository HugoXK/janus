from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class Settings:
    """Local-first settings.

    The default database lives in ``~/.janus/janus.db``. Tests and demos can
    pass ``db_path=":memory:"`` or a temporary path.
    """

    home: Path = Path.home() / ".janus"
    db_path: Optional[Path] = None

    @property
    def database(self) -> str:
        return str(self.db_path) if self.db_path is not None else str(self.home / "janus.db")

    def ensure_home(self) -> Path:
        self.home.mkdir(parents=True, exist_ok=True)
        return self.home


DEFAULT_SETTINGS = Settings()
