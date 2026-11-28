from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from janus.mcp.auth import (
    RESOURCE_SCOPES,
    TOOL_SCOPES,
    ApprovalLedger,
    AuditLedger,
    AuthorizationError,
    Authorizer,
    TokenRegistry,
    canonical_argument_hash,
)
from janus.mcp.service import JanusService
from janus.memory.store import JanusStore

T0 = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


class Clock:
    """Mutable, injectable clock so approvals and the audit trail are testable."""

    def __init__(self, now: datetime = T0) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _registry(*callers: dict[str, Any]) -> TokenRegistry:
    return TokenRegistry.from_mapping({"callers": list(callers)})


def _tokens() -> TokenRegistry:
    return _registry(
        {
            "id": "reader",
            "token": "reader-token",
            "scopes": ["read"],
        },
        {
            "id": "writer",
            "token": "writer-token",
            "scopes": ["read", "write"],
        },
        {
            "id": "admin",
            "token": "admin-token",
            "scopes": ["read", "admin"],
        },
    )


def _authorizer(
    store: JanusStore,
    token: str | None,
    *,
    enabled: bool = True,
    clock: Clock | None = None,
    ttl: int = 900,
    registry: TokenRegistry | None = None,
) -> Authorizer:
    return Authorizer(
        store,
        tokens=registry or _tokens(),
        caller_token=token,
        write_approvals_enabled=enabled,
        approval_ttl_seconds=ttl,
        clock=clock or Clock(),
    )


def _writer(store: JanusStore, **kwargs: Any) -> JanusService:
    return JanusService(store, authorizer=_authorizer(store, "writer-token", **kwargs))


def _admin(store: JanusStore, **kwargs: Any) -> JanusService:
    return JanusService(store, authorizer=_authorizer(store, "admin-token", **kwargs))


def _first_thesis_args(**overrides: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "entity_id": "ACME",
        "statement": "ACME holds its trend.",
        "horizon": "1M",
        "as_of": "2026-01-01T00:00:00+00:00",
        "falsifiers": ["close below the 50-day average"],
    }
    args.update(overrides)
    return args


def _expect(code: str, call, *args: Any, **kwargs: Any) -> AuthorizationError:
    with pytest.raises(AuthorizationError) as excinfo:
        call(*args, **kwargs)
    assert excinfo.value.code == code, excinfo.value.to_dict()
    return excinfo.value


def test_missing_bad_and_expired_tokens_are_typed_and_audited() -> None:
    store = JanusStore(":memory:")
    audit = AuditLedger(store)

    missing = _expect(
        "token_invalid", _authorizer(store, None).require_read, "janus_thesis_list"
    )
    assert "token" in missing.message.lower()
    bad = _expect(
        "token_invalid", _authorizer(store, "not-a-token").require_read, "janus_thesis_list"
    )
    assert "not-a-token" not in json.dumps(bad.to_dict())

    expired_registry = _registry(
        {
            "id": "stale",
            "token": "stale-token",
            "scopes": ["read"],
            "expires_at": (T0 - timedelta(minutes=1)).isoformat(),
        }
    )
    clock = Clock()
    _expect(
        "token_expired",
        _authorizer(store, "stale-token", registry=expired_registry, clock=clock).require_read,
        "janus_thesis_list",
    )

    rows = audit.query()
    assert [row["code"] for row in rows] == ["token_invalid", "token_invalid", "token_expired"]
    assert all(row["tool"] == "janus_thesis_list" for row in rows)


def test_read_scope_is_enforced_on_service_and_resources() -> None:
    store = JanusStore(":memory:")
    tokenless = JanusService(store, authorizer=_authorizer(store, "admin-token"))
    assert tokenless.list_theses() == []

    store_without_read = JanusStore(":memory:")
    service = JanusService(
        store_without_read,
        authorizer=Authorizer(
            store_without_read,
            tokens=_registry({"id": "blind", "token": "blind-token", "scopes": ["write"]}),
            caller_token="blind-token",
            write_approvals_enabled=True,
            clock=Clock(),
        ),
    )
    _expect("scope_denied", service.require_resource, "janus://theses")
    _expect("scope_denied", service.list_theses)
    rows = AuditLedger(store_without_read).query()
    assert rows[-2]["tool"] == "janus://theses"
    assert rows[-2]["code"] == "scope_denied"
    assert rows[-1]["tool"] == "janus_thesis_list"


def test_undeclared_tool_or_resource_fails_closed() -> None:
    store = JanusStore(":memory:")
    authorizer = _authorizer(store, "reader-token")
    _expect("scope_denied", authorizer.require_read, "janus_not_registered")
    _expect("scope_denied", authorizer.require_resource, "janus://not-registered")


def _registrations() -> tuple[set[str], set[str]]:
    """Enumerate what the server actually registers, from its source."""

    import ast
    from pathlib import Path

    source = Path("core/janus/mcp/server.py").read_text()
    tree = ast.parse(source)
    tools: set[str] = set()
    resources: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            target = decorator.func
            if not isinstance(target, ast.Attribute) or not isinstance(
                target.value, ast.Name
            ):
                continue
            if target.value.id != "server":
                continue
            if target.attr == "tool":
                tools.add(node.name)
            elif target.attr == "resource":
                uri = decorator.args[0]
                if isinstance(uri, ast.Constant):
                    resources.add(str(uri.value))
    return tools, resources


def test_every_registered_tool_and_resource_declares_a_scope() -> None:
    from janus.mcp.server import RESOURCES, TOOLS

    assert set(TOOL_SCOPES) == set(TOOLS)
    assert set(RESOURCE_SCOPES) == set(RESOURCES)

    registered_tools, registered_resources = _registrations()
    assert registered_tools == set(TOOLS)
    assert registered_resources == set(RESOURCES)
    assert all(scope in {"read", "write", "admin"} for scope in TOOL_SCOPES.values())
    assert all(scope in {"read", "write", "admin"} for scope in RESOURCE_SCOPES.values())


def test_audit_table_rejects_updates_and_deletes() -> None:
    import sqlite3

    store = JanusStore(":memory:")
    ledger = AuditLedger(store)
    ledger.append(
        recorded_at=T0,
        caller_id="reader",
        tool="janus_thesis_list",
        decision="denied",
        code="scope_denied",
    )
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        store.connection.execute("UPDATE mcp_audit SET decision = 'allowed'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        store.connection.execute("DELETE FROM mcp_audit")


def test_service_bypass_of_fastmcp_wrapper_is_denied() -> None:
    store = JanusStore(":memory:")
    service = _writer(store)
    _expect(
        "approval_required",
        service.create_thesis,
        **_first_thesis_args(),
    )
    assert service.list_theses() == []


def test_write_requires_approval_then_executes_exactly_once() -> None:
    store = JanusStore(":memory:")
    service = _writer(store)

    required = _expect(
        "approval_required", service.create_thesis, **_first_thesis_args()
    )
    assert required.approval_id
    assert service.list_theses() == []

    admin = _admin(store)
    approval = admin.decide_approval(required.approval_id, "approve")
    assert approval["decision"] == "approved"
    assert approval["tool"] == "janus_thesis_create"
    assert approval["argument_hash"] == canonical_argument_hash(
        "janus_thesis_create", _first_thesis_args()
    )

    created = service.create_thesis(**_first_thesis_args())
    assert created["entity_id"] == "ACME"
    assert len(service.list_theses()) == 1

    _expect("approval_consumed", service.create_thesis, **_first_thesis_args())
    assert len(service.list_theses()) == 1


def test_changed_arguments_need_a_new_approval_and_denial_blocks() -> None:
    store = JanusStore(":memory:")
    service = _writer(store)
    admin = _admin(store)

    first = _expect("approval_required", service.create_thesis, **_first_thesis_args())
    admin.decide_approval(first.approval_id, "deny")
    denied = _expect("approval_denied", service.create_thesis, **_first_thesis_args())
    assert denied.approval_id == first.approval_id

    changed = _first_thesis_args(statement="ACME breaks down.")
    second = _expect("approval_required", service.create_thesis, **changed)
    assert second.approval_id != first.approval_id
    assert second.argument_hash != first.argument_hash
    assert service.list_theses() == []


def test_expired_approval_is_rejected() -> None:
    store = JanusStore(":memory:")
    clock = Clock()
    service = _writer(store, clock=clock, ttl=60)
    admin = _admin(store, clock=clock)

    required = _expect("approval_required", service.create_thesis, **_first_thesis_args())
    admin.decide_approval(required.approval_id, "approve")
    clock.now = T0 + timedelta(seconds=61)

    _expect("approval_expired", service.create_thesis, **_first_thesis_args())
    assert service.list_theses() == []


def test_writes_are_disabled_by_default() -> None:
    store = JanusStore(":memory:")
    service = _writer(store, enabled=False)

    _expect("write_disabled", service.create_thesis, **_first_thesis_args())
    assert ApprovalLedger(store).list_all() == []

    disabled_admin = _admin(store, enabled=False)
    _expect("write_disabled", disabled_admin.decide_approval, "apv-does-not-exist", "approve")


def test_concurrent_execution_of_one_approval_succeeds_once() -> None:
    store = JanusStore(":memory:")
    service = _writer(store)
    admin = _admin(store)
    required = _expect("approval_required", service.create_thesis, **_first_thesis_args())
    admin.decide_approval(required.approval_id, "approve")

    barrier = threading.Barrier(2)

    def call() -> Any:
        barrier.wait(timeout=5)
        return service.create_thesis(**_first_thesis_args())

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(call) for _ in range(2)]
        outcomes: list[Any] = []
        for future in futures:
            try:
                outcomes.append(future.result(timeout=10))
            except AuthorizationError as exc:
                outcomes.append(exc)

    created = [item for item in outcomes if isinstance(item, dict)]
    errors = [item for item in outcomes if isinstance(item, AuthorizationError)]
    assert len(created) == 1
    assert [error.code for error in errors] == ["approval_consumed"]
    assert len(service.list_theses()) == 1


def test_audit_is_append_only_ordered_and_as_of_queryable() -> None:
    store = JanusStore(":memory:")
    clock = Clock()
    legacy = _authorizer(store, "reader-token", clock=clock)
    _expect("scope_denied", legacy.require_read, "janus_thesis_create")
    clock.now = T0 + timedelta(minutes=5)
    _expect("scope_denied", legacy.require_read, "janus_not_registered")

    audit = AuditLedger(store)
    as_of_first = audit.query(as_of=T0)
    assert len(as_of_first) == 1
    assert as_of_first[0]["code"] == "scope_denied"
    full = audit.query()
    assert len(full) == 2
    stored = [row["recorded_at"] for row in full]
    assert stored == sorted(stored)
    assert full[0]["seq"] < full[1]["seq"]


def test_tokens_never_appear_in_errors_audit_or_responses() -> None:
    store = JanusStore(":memory:")
    authorizer = _authorizer(store, "reader-token")
    service = JanusService(store, authorizer=authorizer)
    denial = _expect(
        "scope_denied", service.create_thesis, **_first_thesis_args()
    )
    payload = json.dumps(
        {"error": denial.to_dict(), "audit": AuditLedger(store).query()},
        default=str,
    )
    assert "reader-token" not in payload
    assert "writer-token" not in payload
    assert "admin-token" not in payload


def test_canonical_argument_hash_is_stable_and_order_independent() -> None:
    left = canonical_argument_hash(
        "janus_thesis_create", {"b": 2, "a": 1, "nested": {"y": 1, "x": 2}}
    )
    right = canonical_argument_hash(
        "janus_thesis_create", {"nested": {"x": 2, "y": 1}, "a": 1, "b": 2}
    )
    changed = canonical_argument_hash("janus_thesis_create", {"a": 1, "b": 3})
    other_tool = canonical_argument_hash("janus_forecast_create", {"a": 1, "b": 2})
    assert left == right
    assert left != changed
    assert left != other_tool


def test_entity_reads_require_read_scope_and_are_audited() -> None:
    store = JanusStore(":memory:")
    blind = JanusService(
        store,
        authorizer=Authorizer(
            store,
            tokens=_registry({"id": "blind", "token": "blind-token", "scopes": ["write"]}),
            caller_token="blind-token",
            write_approvals_enabled=True,
            clock=Clock(),
        ),
    )
    _expect("scope_denied", blind.resolve_entity, "ACME")
    _expect("scope_denied", blind.get_entity, "ent-1")
    _expect("scope_denied", blind.list_entities)

    rows = AuditLedger(store).query()
    assert [row["tool"] for row in rows] == [
        "janus_entity_resolve",
        "janus_entity_show",
        "janus_entity_list",
    ]
    assert {row["decision"] for row in rows} == {"denied"}

    reader_store = JanusStore(":memory:")
    reader = JanusService(
        reader_store, authorizer=_authorizer(reader_store, "reader-token")
    )
    assert reader.list_entities() == []
    with pytest.raises(KeyError):
        reader.resolve_entity("missing")
    with pytest.raises(KeyError):
        reader.get_entity("missing")


def test_forecast_reads_require_read_scope_and_are_audited() -> None:
    store = JanusStore(":memory:")
    blind = JanusService(
        store,
        authorizer=Authorizer(
            store,
            tokens=_registry({"id": "blind", "token": "blind-token", "scopes": ["write"]}),
            caller_token="blind-token",
            write_approvals_enabled=True,
            clock=Clock(),
        ),
    )
    _expect(
        "scope_denied",
        blind.scenario_tree,
        entity_id="ACME",
        horizon="1M",
        as_of="2026-01-01T00:00:00+00:00",
        direction_probability=0.5,
    )
    _expect("scope_denied", blind.quantile_forecast, [0.01, -0.02, 0.03])

    rows = AuditLedger(store).query()
    assert [row["tool"] for row in rows] == [
        "janus_scenario_tree",
        "janus_quantile_forecast",
    ]
    assert {row["decision"] for row in rows} == {"denied"}

    reader_store = JanusStore(":memory:")
    reader = JanusService(
        reader_store, authorizer=_authorizer(reader_store, "reader-token")
    )
    tree = reader.scenario_tree(
        entity_id="ACME",
        horizon="1M",
        as_of="2026-01-01T00:00:00+00:00",
        direction_probability=0.5,
    )
    assert tree
    quantiles = reader.quantile_forecast([0.01, -0.02, 0.03])
    assert quantiles["width"] >= 0
