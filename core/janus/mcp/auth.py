"""Scoped authorization, approval, and audit for the MCP surface.

The MCP server is local and single-user, but the process boundary is still a
trust boundary: any client that can speak to the stdio transport can call every
tool. This module makes that boundary explicit:

* every registered tool and resource declares one scope (``read``, ``write``,
  ``admin``); an undeclared name is denied (fail closed);
* a caller is identified by a token that maps to a caller id and a scope set;
  tokens are only stored hashed and never appear in errors, audit rows, or
  tool responses;
* a ``write`` tool never runs on the first call. It creates an approval bound
  to caller, tool, canonical argument hash, and expiry, and runs once after an
  ``admin`` caller approves it;
* denials, approval decisions, and executions are appended to an audit table
  that rejects updates and deletes. Queries are ordered deterministically and
  support ``as_of``.

Writes are disabled unless ``JANUS_MCP_WRITE_APPROVALS=1`` is set. The design
and its limits are recorded in ``docs/adr/0005-mcp-scoped-auth.md``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Optional, Sequence

READ = "read"
WRITE = "write"
ADMIN = "admin"
SCOPES = frozenset({READ, WRITE, ADMIN})

#: One scope per MCP tool. A name that is missing here is denied at runtime.
TOOL_SCOPES: dict[str, str] = {
    "janus_version": READ,
    "janus_as_of_query": READ,
    "janus_thesis_create": WRITE,
    "janus_thesis_list": READ,
    "janus_forecast_create": WRITE,
    "janus_forecast_list": READ,
    "janus_forecast_settle": WRITE,
    "janus_review_debrief": WRITE,
    "janus_calibrate": READ,
    "janus_entity_resolve": READ,
    "janus_entity_show": READ,
    "janus_entity_list": READ,
    "janus_security_resolve": READ,
    "janus_universe_members": READ,
    "janus_persona_list": READ,
    "janus_beliefbench_run": READ,
    "janus_scenario_tree": READ,
    "janus_quantile_forecast": READ,
    "janus_corporate_actions": READ,
    "janus_adjust_price": READ,
    "janus_source_spans": READ,
    "janus_source_citation": READ,
    "janus_provenance_trace": READ,
    "janus_mcp_approval_list": ADMIN,
    "janus_mcp_approval_decide": ADMIN,
}

#: One scope per MCP resource. A name that is missing here is denied.
RESOURCE_SCOPES: dict[str, str] = {
    "janus://theses": READ,
    "janus://forecasts": READ,
    "janus://calibration": READ,
    "janus://entities": READ,
    "janus://market": READ,
    "janus://sector": READ,
    "janus://stock": READ,
    "janus://provenance": READ,
}

WRITE_TOOLS = frozenset(name for name, scope in TOOL_SCOPES.items() if scope == WRITE)


class AuthorizationError(Exception):
    """A typed, audited denial or approval failure.

    ``code`` is part of the public contract; the message is safe to log and to
    return to the caller. Tokens are never included.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        approval_id: Optional[str] = None,
        argument_hash: Optional[str] = None,
        expires_at: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.approval_id = approval_id
        self.argument_hash = argument_hash
        self.expires_at = expires_at

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.approval_id is not None:
            payload["approval_id"] = self.approval_id
        if self.argument_hash is not None:
            payload["argument_hash"] = self.argument_hash
        if self.expires_at is not None:
            payload["expires_at"] = self.expires_at
        return payload

    def __str__(self) -> str:  # keep tokens out of tracebacks too
        return f"{self.code}: {self.message}"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def canonical_argument_hash(tool: str, arguments: Mapping[str, Any]) -> str:
    """Hash the tool name and arguments in a stable, order-independent form.

    ``None`` arguments are dropped so that omitting an optional argument and
    passing ``null`` produce the same request (and therefore the same approval).
    """

    normalized = {key: value for key, value in arguments.items() if value is not None}
    canonical = json.dumps(
        {"tool": tool, "arguments": normalized},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _iso(stamp: datetime) -> str:
    if stamp.tzinfo is None or stamp.tzinfo.utcoffset(stamp) is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _parse(value: str) -> datetime:
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp


@dataclass(frozen=True)
class Caller:
    id: str
    scopes: frozenset[str]
    expires_at: Optional[datetime] = None


@dataclass(frozen=True)
class Approval:
    id: str
    caller_id: str
    tool: str
    argument_hash: str
    created_at: datetime
    expires_at: datetime
    decision: str
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "caller_id": self.caller_id,
            "tool": self.tool,
            "argument_hash": self.argument_hash,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "decision": self.decision,
            "decided_by": self.decided_by,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
        }


class TokenRegistry:
    """Token-to-caller mapping loaded from configuration.

    Only SHA-256 digests are kept in memory; the raw token never leaves the
    authenticate call. ``JANUS_MCP_TOKENS`` accepts either ``token`` (hashed on
    load) or a precomputed ``token_sha256``.
    """

    def __init__(self, entries: Sequence[tuple[str, Caller]]) -> None:
        self._entries = tuple(entries)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "TokenRegistry":
        if not isinstance(payload, Mapping):
            raise ValueError("token registry must be an object")
        callers = payload.get("callers", [])
        if not isinstance(callers, list):
            raise ValueError("token registry 'callers' must be a list")
        entries: list[tuple[str, Caller]] = []
        for index, raw in enumerate(callers):
            if not isinstance(raw, Mapping):
                raise ValueError(f"caller #{index} must be an object")
            caller_id = raw.get("id")
            if not isinstance(caller_id, str) or not caller_id.strip():
                raise ValueError(f"caller #{index} needs a non-empty string id")
            token_hash = raw.get("token_sha256")
            token = raw.get("token")
            if token_hash is not None:
                normalized = str(token_hash).strip().lower()
                if len(normalized) != 64:
                    raise ValueError(f"caller {caller_id}: token_sha256 must be 64 hex chars")
            elif token is not None:
                if not str(token):
                    raise ValueError(f"caller {caller_id}: token must not be empty")
                normalized = hash_token(str(token))
            else:
                raise ValueError(f"caller {caller_id}: provide token or token_sha256")
            raw_scopes = raw.get("scopes", [])
            if not isinstance(raw_scopes, list) or not raw_scopes:
                raise ValueError(f"caller {caller_id}: scopes must be a non-empty list")
            scopes = frozenset(str(scope).strip().lower() for scope in raw_scopes)
            unknown = scopes - SCOPES
            if unknown:
                raise ValueError(f"caller {caller_id}: unknown scopes {sorted(unknown)}")
            expires_at: Optional[datetime] = None
            raw_expiry = raw.get("expires_at")
            if raw_expiry:
                expires_at = _parse(str(raw_expiry))
            entries.append((normalized, Caller(caller_id, scopes, expires_at)))
        return cls(entries)

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "TokenRegistry":
        source = os.environ if env is None else env
        raw = source.get("JANUS_MCP_TOKENS", "")
        if not raw.strip():
            return cls([])
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("JANUS_MCP_TOKENS is not valid JSON") from exc
        return cls.from_mapping(payload)

    def authenticate(self, token: Optional[str], now: datetime) -> Caller:
        if not token:
            raise AuthorizationError("token_invalid", "missing caller token")
        digest = hash_token(token)
        matched: Optional[Caller] = None
        for token_hash, caller in self._entries:
            if hmac.compare_digest(digest, token_hash):
                matched = caller
        if matched is None:
            raise AuthorizationError("token_invalid", "unknown caller token")
        if matched.expires_at is not None and matched.expires_at <= now:
            raise AuthorizationError(
                "token_expired", f"caller {matched.id} token expired at {_iso(matched.expires_at)}"
            )
        return matched


class AuditLedger:
    """Append-only audit trail (SQLite triggers reject updates and deletes)."""

    def __init__(self, store: Any) -> None:
        self.store = store

    def append(
        self,
        *,
        recorded_at: datetime,
        caller_id: str,
        tool: str,
        decision: str,
        code: Optional[str] = None,
        argument_hash: Optional[str] = None,
        approval_id: Optional[str] = None,
        detail: str = "",
    ) -> None:
        with self.store.locked():
            self.store.connection.execute(
                """
                INSERT INTO mcp_audit
                    (recorded_at, caller_id, tool, decision, code,
                     argument_hash, approval_id, detail)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _iso(recorded_at),
                    caller_id,
                    tool,
                    decision,
                    code,
                    argument_hash,
                    approval_id,
                    detail,
                ),
            )
            self.store.connection.commit()

    def query(
        self, as_of: Optional[datetime] = None, limit: Optional[int] = None
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT seq, recorded_at, caller_id, tool, decision, code, "
            "argument_hash, approval_id, detail FROM mcp_audit"
        )
        params: list[Any] = []
        if as_of is not None:
            sql += " WHERE recorded_at <= ?"
            params.append(_iso(as_of))
        sql += " ORDER BY recorded_at ASC, seq ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with self.store.locked():
            rows = self.store.connection.execute(sql, params).fetchall()
        return [dict(row) for row in rows]


class ApprovalLedger:
    """Approval records bound to caller, tool, and canonical argument hash."""

    def __init__(self, store: Any) -> None:
        self.store = store

    def create(
        self,
        *,
        caller_id: str,
        tool: str,
        argument_hash: str,
        now: datetime,
        ttl_seconds: int,
    ) -> Approval:
        approval_id = f"apv-{uuid.uuid4().hex[:16]}"
        expires_at = now + timedelta(seconds=ttl_seconds)
        with self.store.locked():
            self.store.connection.execute(
                """
                INSERT INTO mcp_approval
                    (id, caller_id, tool, argument_hash, created_at, expires_at,
                     decision)
                VALUES (?, ?, ?, ?, ?, ?, 'pending')
                """,
                (approval_id, caller_id, tool, argument_hash, _iso(now), _iso(expires_at)),
            )
            self.store.connection.commit()
        return Approval(
            id=approval_id,
            caller_id=caller_id,
            tool=tool,
            argument_hash=argument_hash,
            created_at=now,
            expires_at=expires_at,
            decision="pending",
        )

    def _rows(self, where: str, params: Sequence[Any], order: str) -> list[Approval]:
        sql = (
            "SELECT id, caller_id, tool, argument_hash, created_at, expires_at, "
            "decision, decided_by, decided_at, executed_at FROM mcp_approval "
            f"{where} ORDER BY {order}"
        )
        with self.store.locked():
            rows = self.store.connection.execute(sql, list(params)).fetchall()
        return [self._from_row(row) for row in rows]

    @staticmethod
    def _from_row(row: Any) -> Approval:
        return Approval(
            id=row["id"],
            caller_id=row["caller_id"],
            tool=row["tool"],
            argument_hash=row["argument_hash"],
            created_at=_parse(row["created_at"]),
            expires_at=_parse(row["expires_at"]),
            decision=row["decision"],
            decided_by=row["decided_by"],
            decided_at=_parse(row["decided_at"]) if row["decided_at"] else None,
            executed_at=_parse(row["executed_at"]) if row["executed_at"] else None,
        )

    def latest(self, caller_id: str, tool: str, argument_hash: str) -> Optional[Approval]:
        rows = self._rows(
            "WHERE caller_id = ? AND tool = ? AND argument_hash = ?",
            (caller_id, tool, argument_hash),
            "created_at DESC, rowid DESC",
        )
        return rows[0] if rows else None

    def get(self, approval_id: str) -> Optional[Approval]:
        rows = self._rows("WHERE id = ?", (approval_id,), "rowid ASC")
        return rows[0] if rows else None

    def list_all(self) -> list[Approval]:
        return self._rows("", (), "created_at ASC, rowid ASC")

    def query(self, as_of: Optional[datetime] = None) -> list[Approval]:
        if as_of is None:
            return self.list_all()
        return self._rows(
            "WHERE created_at <= ?", (_iso(as_of),), "created_at ASC, rowid ASC"
        )

    def decide(
        self, approval_id: str, decision: str, decided_by: str, now: datetime
    ) -> Approval:
        with self.store.locked():
            cursor = self.store.connection.execute(
                """
                UPDATE mcp_approval
                SET decision = ?, decided_by = ?, decided_at = ?
                WHERE id = ? AND decision = 'pending'
                """,
                (decision, decided_by, _iso(now), approval_id),
            )
            self.store.connection.commit()
            changed = cursor.rowcount
        approval = self.get(approval_id)
        if approval is None:
            raise AuthorizationError("approval_invalid", f"unknown approval: {approval_id}")
        if changed != 1:
            raise AuthorizationError(
                "approval_invalid",
                f"approval {approval_id} already decided as {approval.decision}",
            )
        return approval

    def claim(self, approval_id: str, now: datetime) -> bool:
        """Atomically mark one approved approval as executed; exactly once."""

        with self.store.locked():
            cursor = self.store.connection.execute(
                """
                UPDATE mcp_approval
                SET executed_at = ?
                WHERE id = ? AND decision = 'approved' AND executed_at IS NULL
                """,
                (_iso(now), approval_id),
            )
            self.store.connection.commit()
            return cursor.rowcount == 1


class Authorizer:
    """Enforces scope, approval, and audit rules for one caller token."""

    def __init__(
        self,
        store: Any,
        *,
        tokens: TokenRegistry,
        caller_token: Optional[str],
        write_approvals_enabled: bool = False,
        approval_ttl_seconds: int = 900,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        if approval_ttl_seconds <= 0:
            raise ValueError("approval_ttl_seconds must be > 0")
        self.store = store
        self.tokens = tokens
        self._caller_token = caller_token
        self.write_approvals_enabled = write_approvals_enabled
        self.approval_ttl_seconds = approval_ttl_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._audit = AuditLedger(store)
        self._approvals = ApprovalLedger(store)

    def now(self) -> datetime:
        stamp = self._clock()
        if stamp.tzinfo is None or stamp.tzinfo.utcoffset(stamp) is None:
            return stamp.replace(tzinfo=timezone.utc)
        return stamp.astimezone(timezone.utc)

    # -- internal -------------------------------------------------------
    def _authenticate(self, name: str) -> Caller:
        try:
            return self.tokens.authenticate(self._caller_token, self.now())
        except AuthorizationError as exc:
            self._record(
                caller_id="unknown",
                tool=name,
                decision="denied",
                code=exc.code,
                detail=exc.message,
            )
            raise

    def _record(
        self,
        *,
        caller_id: str,
        tool: str,
        decision: str,
        code: Optional[str] = None,
        argument_hash: Optional[str] = None,
        approval_id: Optional[str] = None,
        detail: str = "",
    ) -> None:
        self._audit.append(
            recorded_at=self.now(),
            caller_id=caller_id,
            tool=tool,
            decision=decision,
            code=code,
            argument_hash=argument_hash,
            approval_id=approval_id,
            detail=detail,
        )

    def _deny(
        self,
        *,
        caller: Caller,
        name: str,
        code: str,
        message: str,
        argument_hash: Optional[str] = None,
        approval_id: Optional[str] = None,
        expires_at: Optional[str] = None,
        decision: str = "denied",
    ) -> None:
        self._record(
            caller_id=caller.id,
            tool=name,
            decision=decision,
            code=code,
            argument_hash=argument_hash,
            approval_id=approval_id,
            detail=message,
        )
        raise AuthorizationError(
            code,
            message,
            approval_id=approval_id,
            argument_hash=argument_hash,
            expires_at=expires_at,
        )

    # -- read side ------------------------------------------------------
    def require_read(self, tool: str) -> Caller:
        return self.require_tool(tool, READ)

    def require_tool(self, tool: str, required: Optional[str] = None) -> Caller:
        caller = self._authenticate(tool)
        declared = TOOL_SCOPES.get(tool)
        if declared is None:
            self._deny(
                caller=caller,
                name=tool,
                code="scope_denied",
                message=f"{tool} has no declared scope; denied",
            )
        if required is not None and declared != required:
            self._deny(
                caller=caller,
                name=tool,
                code="scope_denied",
                message=f"{tool} declares {declared}, not {required}; denied",
            )
        if declared not in caller.scopes:
            self._deny(
                caller=caller,
                name=tool,
                code="scope_denied",
                message=f"caller {caller.id} lacks the {declared} scope for {tool}",
            )
        return caller

    def require_resource(self, uri: str) -> Caller:
        caller = self._authenticate(uri)
        if RESOURCE_SCOPES.get(uri) is None:
            self._deny(
                caller=caller,
                name=uri,
                code="scope_denied",
                message=f"{uri} has no declared scope; denied",
            )
        if READ not in caller.scopes:
            self._deny(
                caller=caller,
                name=uri,
                code="scope_denied",
                message=f"caller {caller.id} lacks the read scope for {uri}",
            )
        return caller

    # -- write side -----------------------------------------------------
    def authorize_write(
        self, tool: str, arguments: Mapping[str, Any], action: Callable[[], Any]
    ) -> Any:
        caller = self._authenticate(tool)
        declared = TOOL_SCOPES.get(tool)
        if declared is None:
            self._deny(
                caller=caller,
                name=tool,
                code="scope_denied",
                message=f"{tool} has no declared scope; denied",
            )
        if declared != WRITE:
            self._deny(
                caller=caller,
                name=tool,
                code="scope_denied",
                message=f"{tool} declares {declared}, not {WRITE}; denied",
            )
        if WRITE not in caller.scopes:
            self._deny(
                caller=caller,
                name=tool,
                code="scope_denied",
                message=f"caller {caller.id} lacks the {declared} scope for {tool}",
            )
        if not self.write_approvals_enabled:
            self._deny(
                caller=caller,
                name=tool,
                code="write_disabled",
                message=(
                    "writes are disabled; set JANUS_MCP_WRITE_APPROVALS=1 and "
                    "grant an admin caller the admin scope"
                ),
            )

        argument_hash = canonical_argument_hash(tool, arguments)
        now = self.now()
        approval = self._approvals.latest(caller.id, tool, argument_hash)
        if approval is None:
            approval = self._approvals.create(
                caller_id=caller.id,
                tool=tool,
                argument_hash=argument_hash,
                now=now,
                ttl_seconds=self.approval_ttl_seconds,
            )
            self._deny(
                caller=caller,
                name=tool,
                code="approval_required",
                message=(
                    f"approval required for {tool}; approve {approval.id} "
                    "with an admin caller"
                ),
                argument_hash=argument_hash,
                approval_id=approval.id,
                expires_at=_iso(approval.expires_at),
                decision="approval_required",
            )

        if approval.decision == "denied":
            self._deny(
                caller=caller,
                name=tool,
                code="approval_denied",
                message=f"approval {approval.id} was denied",
                argument_hash=argument_hash,
                approval_id=approval.id,
                decision="denied",
            )
        if approval.decision == "pending":
            self._deny(
                caller=caller,
                name=tool,
                code="approval_required",
                message=f"approval {approval.id} is still pending",
                argument_hash=argument_hash,
                approval_id=approval.id,
                expires_at=_iso(approval.expires_at),
                decision="approval_required",
            )
        if approval.expires_at <= now:
            replacement = self._approvals.create(
                caller_id=caller.id,
                tool=tool,
                argument_hash=argument_hash,
                now=now,
                ttl_seconds=self.approval_ttl_seconds,
            )
            self._deny(
                caller=caller,
                name=tool,
                code="approval_expired",
                message=(
                    f"approval {approval.id} expired at {_iso(approval.expires_at)}; "
                    f"approve replacement {replacement.id}"
                ),
                argument_hash=argument_hash,
                approval_id=approval.id,
                expires_at=_iso(approval.expires_at),
                decision="approval_expired",
            )
        if approval.executed_at is not None:
            self._deny(
                caller=caller,
                name=tool,
                code="approval_consumed",
                message=f"approval {approval.id} was already executed",
                argument_hash=argument_hash,
                approval_id=approval.id,
                decision="denied",
            )
        if not self._approvals.claim(approval.id, now):
            self._deny(
                caller=caller,
                name=tool,
                code="approval_consumed",
                message=f"approval {approval.id} was already executed",
                argument_hash=argument_hash,
                approval_id=approval.id,
                decision="denied",
            )

        self._record(
            caller_id=caller.id,
            tool=tool,
            decision="executed",
            argument_hash=argument_hash,
            approval_id=approval.id,
        )
        try:
            return action()
        except BaseException:
            self._record(
                caller_id=caller.id,
                tool=tool,
                decision="execution_failed",
                code="execution_failed",
                argument_hash=argument_hash,
                approval_id=approval.id,
            )
            raise

    # -- admin side -----------------------------------------------------
    def list_approvals(self, as_of: Optional[datetime] = None) -> list[dict[str, Any]]:
        self.require_tool("janus_mcp_approval_list", ADMIN)
        return [approval.to_dict() for approval in self._approvals.query(as_of)]

    def decide(self, approval_id: str, decision: str) -> dict[str, Any]:
        caller = self.require_tool("janus_mcp_approval_decide", ADMIN)
        if not self.write_approvals_enabled:
            self._deny(
                caller=caller,
                name="janus_mcp_approval_decide",
                code="write_disabled",
                message="writes are disabled; set JANUS_MCP_WRITE_APPROVALS=1 to decide approvals",
                approval_id=approval_id,
            )
        normalized = {"approve": "approved", "deny": "denied"}.get(decision, decision)
        if normalized not in {"approved", "denied"}:
            self._deny(
                caller=caller,
                name="janus_mcp_approval_decide",
                code="approval_invalid",
                message="decision must be approve or deny",
                approval_id=approval_id,
            )
        try:
            approval = self._approvals.decide(
                approval_id, normalized, caller.id, self.now()
            )
        except AuthorizationError as exc:
            self._record(
                caller_id=caller.id,
                tool="janus_mcp_approval_decide",
                decision="denied",
                code=exc.code,
                approval_id=approval_id,
                detail=exc.message,
            )
            raise
        self._record(
            caller_id=caller.id,
            tool="janus_mcp_approval_decide",
            decision=normalized,
            approval_id=approval.id,
            detail=f"decided by {caller.id}",
        )
        return approval.to_dict()

    def audit(self, as_of: Optional[datetime] = None, limit: Optional[int] = None) -> list[dict[str, Any]]:
        return self._audit.query(as_of=as_of, limit=limit)


def authorizer_from_env(
    store: Any,
    env: Optional[Mapping[str, str]] = None,
    clock: Optional[Callable[[], datetime]] = None,
) -> Authorizer:
    """Build an authorizer from ``JANUS_MCP_*`` environment variables.

    Fail closed: a missing registry means no caller can authenticate, and
    writes stay disabled unless ``JANUS_MCP_WRITE_APPROVALS`` is truthy.
    """

    source = os.environ if env is None else env
    enabled = source.get("JANUS_MCP_WRITE_APPROVALS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    raw_ttl = source.get("JANUS_MCP_APPROVAL_TTL_SECONDS", "900").strip() or "900"
    try:
        ttl = int(raw_ttl)
    except ValueError as exc:
        raise ValueError("JANUS_MCP_APPROVAL_TTL_SECONDS must be an integer") from exc
    return Authorizer(
        store,
        tokens=TokenRegistry.from_env(source),
        caller_token=source.get("JANUS_MCP_TOKEN"),
        write_approvals_enabled=enabled,
        approval_ttl_seconds=ttl,
        clock=clock,
    )
