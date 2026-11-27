from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from .store import JanusStore


def _stamp(value: datetime, name: str) -> str:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


@dataclass(frozen=True)
class Security:
    id: str
    entity_id: str
    symbol: str
    valid_from: datetime
    valid_to: Optional[datetime] = None
    exchange: str = ""
    currency: str = ""
    share_class: str = ""
    source: str = "manual"

    def __post_init__(self) -> None:
        _stamp(self.valid_from, "valid_from")
        if self.valid_to is not None:
            _stamp(self.valid_to, "valid_to")
            if self.valid_to <= self.valid_from:
                raise ValueError("valid_to must be after valid_from")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "entity_id": self.entity_id,
            "symbol": self.symbol,
            "exchange": self.exchange,
            "currency": self.currency,
            "share_class": self.share_class,
            "valid_from": self.valid_from.isoformat(),
            "valid_to": self.valid_to.isoformat() if self.valid_to else None,
            "source": self.source,
        }


@dataclass(frozen=True)
class Membership:
    universe: str
    security_id: str
    valid_from: datetime
    valid_to: Optional[datetime] = None
    source: str = "manual"

    def __post_init__(self) -> None:
        _stamp(self.valid_from, "valid_from")
        if self.valid_to is not None:
            _stamp(self.valid_to, "valid_to")
            if self.valid_to <= self.valid_from:
                raise ValueError("valid_to must be after valid_from")

    def to_dict(self) -> dict[str, Any]:
        return {
            "universe": self.universe,
            "security_id": self.security_id,
            "valid_from": self.valid_from.isoformat(),
            "valid_to": self.valid_to.isoformat() if self.valid_to else None,
            "source": self.source,
        }


class SecurityMaster:
    """Point-in-time symbol and universe membership registry."""

    def __init__(self, store: JanusStore) -> None:
        self.store = store

    def add_security(self, security: Security) -> None:
        self.store.connection.execute(
            """
            INSERT INTO security
            (id, entity_id, symbol, exchange, currency, share_class, valid_from, valid_to, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                entity_id = excluded.entity_id,
                symbol = excluded.symbol,
                exchange = excluded.exchange,
                currency = excluded.currency,
                share_class = excluded.share_class,
                valid_from = excluded.valid_from,
                valid_to = excluded.valid_to,
                source = excluded.source
            """,
            (
                security.id,
                security.entity_id,
                security.symbol.upper(),
                security.exchange,
                security.currency,
                security.share_class,
                _stamp(security.valid_from, "valid_from"),
                _stamp(security.valid_to, "valid_to") if security.valid_to else None,
                security.source,
            ),
        )
        self.store.connection.commit()

    def add_membership(self, membership: Membership) -> None:
        if self.get_security(membership.security_id) is None:
            raise KeyError(f"unknown security: {membership.security_id}")
        self.store.connection.execute(
            """
            INSERT INTO universe_membership
            (universe, security_id, valid_from, valid_to, source)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                membership.universe,
                membership.security_id,
                _stamp(membership.valid_from, "valid_from"),
                _stamp(membership.valid_to, "valid_to") if membership.valid_to else None,
                membership.source,
            ),
        )
        self.store.connection.commit()

    def get_security(self, security_id: str) -> Optional[Security]:
        row = self.store.connection.execute(
            "SELECT * FROM security WHERE id = ?", (security_id,)
        ).fetchone()
        return self._row_to_security(row) if row else None

    def resolve(
        self, symbol: str, as_of: datetime, *, exchange: Optional[str] = None
    ) -> Optional[Security]:
        stamp = _stamp(as_of, "as_of")
        sql = """
            SELECT * FROM security
            WHERE upper(symbol) = upper(?)
              AND valid_from <= ?
              AND (valid_to IS NULL OR valid_to > ?)
        """
        params: list[object] = [symbol, stamp, stamp]
        if exchange is not None:
            sql += " AND upper(exchange) = upper(?)"
            params.append(exchange)
        sql += " ORDER BY valid_from DESC, id LIMIT 1"
        row = self.store.connection.execute(sql, params).fetchone()
        return self._row_to_security(row) if row else None

    def history(self, symbol: str) -> list[Security]:
        rows = self.store.connection.execute(
            "SELECT * FROM security WHERE upper(symbol) = upper(?) "
            "ORDER BY valid_from, id",
            (symbol,),
        ).fetchall()
        return [self._row_to_security(row) for row in rows]

    def members(self, universe: str, as_of: datetime) -> list[Security]:
        stamp = _stamp(as_of, "as_of")
        rows = self.store.connection.execute(
            """
            SELECT security.* FROM universe_membership
            JOIN security ON security.id = universe_membership.security_id
            WHERE universe_membership.universe = ?
              AND universe_membership.valid_from <= ?
              AND (universe_membership.valid_to IS NULL OR universe_membership.valid_to > ?)
              AND security.valid_from <= ?
              AND (security.valid_to IS NULL OR security.valid_to > ?)
            ORDER BY security.symbol, security.valid_from
            """,
            (universe, stamp, stamp, stamp, stamp),
        ).fetchall()
        return [self._row_to_security(row) for row in rows]

    def membership_history(
        self, universe: str, security_id: Optional[str] = None
    ) -> list[Membership]:
        sql = "SELECT * FROM universe_membership WHERE universe = ?"
        params: list[object] = [universe]
        if security_id is not None:
            sql += " AND security_id = ?"
            params.append(security_id)
        sql += " ORDER BY valid_from, id"
        rows = self.store.connection.execute(sql, params).fetchall()
        return [
            Membership(
                universe=row["universe"],
                security_id=row["security_id"],
                valid_from=_dt(row["valid_from"]),
                valid_to=_dt(row["valid_to"]) if row["valid_to"] else None,
                source=row["source"],
            )
            for row in rows
        ]

    @staticmethod
    def _row_to_security(row) -> Security:
        return Security(
            id=row["id"],
            entity_id=row["entity_id"],
            symbol=row["symbol"],
            exchange=row["exchange"],
            currency=row["currency"],
            share_class=row["share_class"],
            valid_from=_dt(row["valid_from"]),
            valid_to=_dt(row["valid_to"]) if row["valid_to"] else None,
            source=row["source"],
        )
