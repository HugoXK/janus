from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from .models import utcnow
from .store import JanusStore


@dataclass(frozen=True)
class SourceSpan:
    id: str
    observation_id: str
    blob_hash: str
    locator: str
    excerpt: str
    start_offset: Optional[int] = None
    end_offset: Optional[int] = None
    source: str = "manual"
    created_at: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.locator:
            raise ValueError("locator is required")
        if not self.excerpt.strip():
            raise ValueError("excerpt is required")
        if self.start_offset is not None and self.start_offset < 0:
            raise ValueError("start_offset must be >= 0")
        if self.end_offset is not None and self.end_offset < 0:
            raise ValueError("end_offset must be >= 0")
        if (
            self.start_offset is not None
            and self.end_offset is not None
            and self.end_offset < self.start_offset
        ):
            raise ValueError("end_offset must be >= start_offset")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "observation_id": self.observation_id,
            "blob_hash": self.blob_hash,
            "locator": self.locator,
            "excerpt": self.excerpt,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "source": self.source,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class Citation:
    observation_id: str
    span_id: str
    source: str
    published_at: str
    locator: str
    excerpt: str
    raw_uri: Optional[str]
    raw_hash: str
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "span_id": self.span_id,
            "source": self.source,
            "published_at": self.published_at,
            "locator": self.locator,
            "excerpt": self.excerpt,
            "raw_uri": self.raw_uri,
            "raw_hash": self.raw_hash,
            "text": self.text,
        }


class SpanStore:
    """Exact source spans attached to observations."""

    def __init__(self, store: JanusStore) -> None:
        self.store = store

    def add(self, span: SourceSpan) -> None:
        observation = self.store.get_observation(span.observation_id)
        if observation is None:
            raise KeyError(f"unknown observation: {span.observation_id}")
        if observation.raw_hash != span.blob_hash:
            raise ValueError(
                "span blob_hash must match the observation raw_hash"
            )
        self.store.connection.execute(
            """
            INSERT INTO source_span
            (id, observation_id, blob_hash, locator, excerpt, start_offset,
             end_offset, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                observation_id = excluded.observation_id,
                blob_hash = excluded.blob_hash,
                locator = excluded.locator,
                excerpt = excluded.excerpt,
                start_offset = excluded.start_offset,
                end_offset = excluded.end_offset,
                source = excluded.source
            """,
            (
                span.id,
                span.observation_id,
                span.blob_hash,
                span.locator,
                span.excerpt,
                span.start_offset,
                span.end_offset,
                span.source,
                span.created_at or utcnow().isoformat(),
            ),
        )
        self.store.connection.commit()

    def list(self, observation_id: str) -> list[SourceSpan]:
        rows = self.store.connection.execute(
            "SELECT * FROM source_span WHERE observation_id = ? ORDER BY locator, id",
            (observation_id,),
        ).fetchall()
        return [self._row(row) for row in rows]

    def show(self, span_id: str) -> Optional[SourceSpan]:
        row = self.store.connection.execute(
            "SELECT * FROM source_span WHERE id = ?", (span_id,)
        ).fetchone()
        return self._row(row) if row else None

    def citation(self, observation_id: str, *, span_id: Optional[str] = None) -> Citation:
        observation = self.store.get_observation(observation_id)
        if observation is None:
            raise KeyError(f"unknown observation: {observation_id}")
        spans = self.list(observation_id)
        if span_id is not None:
            spans = [span for span in spans if span.id == span_id]
        if not spans:
            raise KeyError(f"no source span for observation: {observation_id}")
        span = spans[0]
        where = observation.raw_uri or observation.raw_hash
        excerpt_hash = hashlib.sha256(span.excerpt.encode("utf-8")).hexdigest()[:12]
        text = (
            f"{observation.source} {observation.published_at.isoformat()} "
            f"{where} {span.locator} [{excerpt_hash}]"
        )
        return Citation(
            observation_id=observation.id,
            span_id=span.id,
            source=observation.source,
            published_at=observation.published_at.isoformat(),
            locator=span.locator,
            excerpt=span.excerpt,
            raw_uri=observation.raw_uri,
            raw_hash=observation.raw_hash,
            text=text,
        )

    @staticmethod
    def _row(row) -> SourceSpan:
        return SourceSpan(
            id=row["id"],
            observation_id=row["observation_id"],
            blob_hash=row["blob_hash"],
            locator=row["locator"],
            excerpt=row["excerpt"],
            start_offset=row["start_offset"],
            end_offset=row["end_offset"],
            source=row["source"],
            created_at=row["created_at"],
        )
