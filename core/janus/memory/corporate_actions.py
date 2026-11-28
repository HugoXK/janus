from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from .store import JanusStore

ACTION_TYPES = {
    "split",
    "cash_dividend",
    "stock_dividend",
    "merger",
    "spinoff",
    "symbol_change",
}
MANUAL_ACTION_TYPES = {"merger", "spinoff", "symbol_change"}


def _stamp(value: datetime, name: str) -> str:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True)
class CorporateAction:
    id: str
    security_id: str
    action_type: str
    effective_at: datetime
    ratio: Optional[float] = None
    cash_amount: Optional[float] = None
    currency: str = ""
    related_security_id: Optional[str] = None
    source: str = "manual"
    raw_hash: str = ""
    payload: Optional[dict[str, Any]] = None

    def __post_init__(self) -> None:
        if self.action_type not in ACTION_TYPES:
            raise ValueError(f"unknown action type: {self.action_type}")
        _stamp(self.effective_at, "effective_at")
        if self.action_type in {"split", "stock_dividend"}:
            if self.ratio is None or self.ratio <= 0:
                raise ValueError(f"{self.action_type} needs a positive ratio")
        if self.action_type == "cash_dividend":
            if self.cash_amount is None or self.cash_amount <= 0:
                raise ValueError("cash_dividend needs a positive cash_amount")
        if self.action_type in {"merger", "spinoff"} and not self.related_security_id:
            raise ValueError(f"{self.action_type} needs related_security_id")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "security_id": self.security_id,
            "action_type": self.action_type,
            "effective_at": self.effective_at.isoformat(),
            "ratio": self.ratio,
            "cash_amount": self.cash_amount,
            "currency": self.currency,
            "related_security_id": self.related_security_id,
            "source": self.source,
            "raw_hash": self.raw_hash,
            "payload": self.payload or {},
        }


@dataclass(frozen=True)
class Adjustment:
    security_id: str
    as_of: str
    split_factor: float
    cash_dividends: float
    action_ids: tuple[str, ...]
    manual_action_ids: tuple[str, ...]
    basis: str


class CorporateActionLedger:
    """Append-only corporate actions with a deterministic adjustment basis."""

    def __init__(self, store: JanusStore) -> None:
        self.store = store

    def add(self, action: CorporateAction) -> None:
        self.store.connection.execute(
            """
            INSERT INTO corporate_action
            (id, security_id, action_type, effective_at, ratio, cash_amount,
             currency, related_security_id, source, raw_hash, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                security_id = excluded.security_id,
                action_type = excluded.action_type,
                effective_at = excluded.effective_at,
                ratio = excluded.ratio,
                cash_amount = excluded.cash_amount,
                currency = excluded.currency,
                related_security_id = excluded.related_security_id,
                source = excluded.source,
                raw_hash = excluded.raw_hash,
                payload = excluded.payload
            """,
            (
                action.id,
                action.security_id,
                action.action_type,
                _stamp(action.effective_at, "effective_at"),
                action.ratio,
                action.cash_amount,
                action.currency,
                action.related_security_id,
                action.source,
                action.raw_hash,
                json.dumps(action.payload or {}, sort_keys=True, default=str),
            ),
        )
        self.store.connection.commit()

    def list(
        self, security_id: Optional[str] = None, *, as_of: Optional[datetime] = None
    ) -> list[CorporateAction]:
        sql = "SELECT * FROM corporate_action"
        clauses: list[str] = []
        params: list[object] = []
        if security_id is not None:
            clauses.append("security_id = ?")
            params.append(security_id)
        if as_of is not None:
            clauses.append("effective_at <= ?")
            params.append(_stamp(as_of, "as_of"))
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY effective_at, id"
        rows = self.store.connection.execute(sql, params).fetchall()
        return [self._row_to_action(row) for row in rows]

    def adjustment(self, security_id: str, as_of: datetime) -> Adjustment:
        actions = self.list(security_id, as_of=as_of)
        split_factor = 1.0
        cash = 0.0
        manual: list[str] = []
        basis: list[str] = []
        for action in actions:
            if action.action_type in {"split", "stock_dividend"}:
                ratio = float(action.ratio or 0.0)
                split_factor *= ratio
                basis.append(f"{action.action_type}:{ratio:g}")
            elif action.action_type == "cash_dividend":
                cash += float(action.cash_amount or 0.0)
                basis.append(f"cash_dividend:{action.cash_amount:g}")
            else:
                manual.append(action.id)
        if not basis:
            basis.append("raw")
        if manual:
            basis.append("manual:" + ",".join(manual))
        return Adjustment(
            security_id=security_id,
            as_of=_stamp(as_of, "as_of"),
            split_factor=split_factor,
            cash_dividends=cash,
            action_ids=tuple(action.id for action in actions),
            manual_action_ids=tuple(manual),
            basis="; ".join(basis),
        )

    def adjust_price(
        self, security_id: str, raw_price: float, as_of: datetime
    ) -> dict[str, Any]:
        adjustment = self.adjustment(security_id, as_of)
        return {
            "security_id": security_id,
            "raw_price": float(raw_price),
            "adjusted_price": float(raw_price) / adjustment.split_factor,
            "split_factor": adjustment.split_factor,
            "cash_dividends": adjustment.cash_dividends,
            "basis": adjustment.basis,
            "manual_action_ids": list(adjustment.manual_action_ids),
        }

    @staticmethod
    def _row_to_action(row) -> CorporateAction:
        return CorporateAction(
            id=row["id"],
            security_id=row["security_id"],
            action_type=row["action_type"],
            effective_at=datetime.fromisoformat(row["effective_at"]),
            ratio=row["ratio"],
            cash_amount=row["cash_amount"],
            currency=row["currency"],
            related_security_id=row["related_security_id"],
            source=row["source"],
            raw_hash=row["raw_hash"],
            payload=json.loads(row["payload"]),
        )
