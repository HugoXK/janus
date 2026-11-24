from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from ..memory.models import Thesis, ThesisStatus
from ..memory.store import JanusStore


class ThesisTracker:
    """Create and update explicit market beliefs."""

    def __init__(self, store: JanusStore) -> None:
        self.store = store

    def create(
        self,
        *,
        entity_id: str,
        statement: str,
        horizon: str,
        as_of: datetime,
        persona_id: Optional[str] = None,
        assumptions: Optional[list[str]] = None,
        catalysts: Optional[list[str]] = None,
        risks: Optional[list[str]] = None,
        falsifiers: Optional[list[str]] = None,
    ) -> Thesis:
        thesis = Thesis(
            id=uuid4().hex,
            entity_id=entity_id,
            persona_id=persona_id,
            horizon=horizon,
            statement=statement,
            assumptions=assumptions or [],
            catalysts=catalysts or [],
            risks=risks or [],
            falsifiers=falsifiers or [],
            as_of=as_of,
        )
        self.store.insert_thesis(thesis)
        return thesis

    def update_status(self, thesis_id: str, status: ThesisStatus) -> None:
        self.store.update_thesis_status(thesis_id, status)

    def list_active(self) -> list[Thesis]:
        return self.store.list_theses(status=ThesisStatus.active)
