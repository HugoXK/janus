from __future__ import annotations

import builtins

from dataclasses import dataclass
from typing import Any, Optional

from .store import JanusStore


def normalize_alias(alias: str) -> str:
    return " ".join(alias.strip().casefold().split())


@dataclass(frozen=True)
class Entity:
    id: str
    name: str
    ticker: Optional[str] = None
    cik: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "ticker": self.ticker,
            "cik": self.cik,
            "sector": self.sector,
            "industry": self.industry,
        }


@dataclass(frozen=True)
class EntityAlias:
    alias: str
    entity_id: str
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {"alias": self.alias, "entity_id": self.entity_id, "source": self.source}


class EntityGraph:
    """A small entity/alias graph for tickers, CIKs, and names."""

    def __init__(self, store: JanusStore) -> None:
        self.store = store

    def upsert(self, entity: Entity) -> None:
        self.store.connection.execute(
            """
            INSERT INTO entity (id, name, ticker, cik, sector, industry)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                ticker = excluded.ticker,
                cik = excluded.cik,
                sector = excluded.sector,
                industry = excluded.industry
            """,
            (
                entity.id,
                entity.name,
                entity.ticker,
                entity.cik,
                entity.sector,
                entity.industry,
            ),
        )
        self.store.connection.commit()

    def add_alias(self, alias: str, entity_id: str, source: str = "manual") -> None:
        normalized = normalize_alias(alias)
        if not normalized:
            raise ValueError("alias must not be empty")
        self.store.connection.execute(
            """
            INSERT INTO entity_alias (alias, normalized, entity_id, source)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(normalized) DO UPDATE SET
                alias = excluded.alias,
                entity_id = excluded.entity_id,
                source = excluded.source
            """,
            (alias.strip(), normalized, entity_id, source),
        )
        self.store.connection.commit()

    def get(self, entity_id: str) -> Optional[Entity]:
        row = self.store.connection.execute(
            "SELECT * FROM entity WHERE id = ?", (entity_id,)
        ).fetchone()
        return self._row_to_entity(row) if row else None

    def resolve(self, alias: str) -> Optional[Entity]:
        row = self.store.connection.execute(
            """
            SELECT entity.* FROM entity
            JOIN entity_alias ON entity_alias.entity_id = entity.id
            WHERE entity_alias.normalized = ?
            """,
            (normalize_alias(alias),),
        ).fetchone()
        return self._row_to_entity(row) if row else None

    def list(self, limit: int = 200) -> list[Entity]:
        if limit < 0:
            raise ValueError("limit must be >= 0")
        rows = self.store.connection.execute(
            "SELECT id, name, ticker, cik, sector, industry FROM entity "
            "ORDER BY id LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_entity(row) for row in rows]

    def aliases(self, entity_id: str) -> builtins.list[EntityAlias]:
        rows = self.store.connection.execute(
            "SELECT alias, entity_id, source FROM entity_alias WHERE entity_id = ? ORDER BY alias",
            (entity_id,),
        ).fetchall()
        return [
            EntityAlias(
                alias=row["alias"],
                entity_id=row["entity_id"],
                source=row["source"],
            )
            for row in rows
        ]

    @staticmethod
    def _row_to_entity(row) -> Entity:
        return Entity(
            id=row["id"],
            name=row["name"],
            ticker=row["ticker"],
            cik=row["cik"],
            sector=row["sector"],
            industry=row["industry"],
        )
