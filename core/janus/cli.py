from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer

from . import __version__
from .config import load_settings
from .contracts import SCHEMA_VERSION, check_schema, write_schema
from .data.blob import LocalBlobStore
from .demo import run_demo
from .forecast.registry import (
    ArtifactCorruptError,
    ArtifactNotFoundError,
    ModelArtifact,
    ModelRegistry,
)
from .memory.audit import AuditChain, AuditError
from .memory.migrations import apply_migrations, current_version
from .memory.retention import (
    RetentionPolicy,
    RetentionRule,
    apply_retention,
    export_redacted,
)
from .memory.models import ObservationKind
from .memory.corporate_actions import CorporateActionLedger
from .memory.security_master import SecurityMaster
from .memory.spans import SpanStore
from .memory.store import JanusStore

app = typer.Typer(
    add_completion=False,
    help="Janus — a market agent with memory and foresight.",
)
config_app = typer.Typer(help="Inspect and validate local configuration.")
schema_app = typer.Typer(help="Export and verify the domain contract schema.")
model_app = typer.Typer(help="Inspect content-addressed model artifacts.")
blob_app = typer.Typer(help="Inspect and garbage-collect content-addressed blobs.")
security_app = typer.Typer(help="Resolve point-in-time securities.")
universe_app = typer.Typer(help="Query point-in-time universe membership.")
actions_app = typer.Typer(help="Inspect corporate actions and price adjustments.")
spans_app = typer.Typer(help="Inspect exact source spans and citations.")
retention_app = typer.Typer(help="Apply retention and export redacted data.")
mcp_app = typer.Typer(help="Inspect scoped MCP approvals and audit records.")
audit_app = typer.Typer(help="Verify and export the tamper-evident audit chain.")
app.add_typer(config_app, name="config")
app.add_typer(schema_app, name="schema")
app.add_typer(model_app, name="model")
app.add_typer(blob_app, name="blob")
app.add_typer(security_app, name="security")
app.add_typer(universe_app, name="universe")
app.add_typer(actions_app, name="actions")
app.add_typer(spans_app, name="spans")
app.add_typer(retention_app, name="retention")
app.add_typer(mcp_app, name="mcp")
app.add_typer(audit_app, name="audit")


@app.command()
def version() -> None:
    """Print the Janus version and domain schema version."""

    typer.echo(f"janus {__version__} (schema {SCHEMA_VERSION})")


@app.command()
def demo() -> None:
    """Run the offline end-to-end demonstration."""

    run_demo()


@app.command()
def asof(
    entity: str = typer.Argument(..., help="Entity id, e.g. ACME"),
    when: str = typer.Argument(..., help="ISO timestamp, e.g. 2026-01-15"),
    kind: Optional[str] = typer.Option(None, help="Observation kind filter"),
    mode: str = typer.Option("published", help="published or observed"),
    snapshot: Optional[str] = typer.Option(None, help="Snapshot id filter"),
    limit: Optional[int] = typer.Option(None, help="Maximum rows"),
    offset: int = typer.Option(0, help="Rows to skip"),
    db: Optional[str] = typer.Option(None, help="SQLite path (default: from config)"),
) -> None:
    """Query observations that were knowable at a point in time."""

    try:
        stamp = datetime.fromisoformat(when)
    except ValueError as exc:
        raise typer.BadParameter("use an ISO timestamp, e.g. 2026-01-15") from exc
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)

    observation_kind = None
    if kind is not None:
        try:
            observation_kind = ObservationKind(kind)
        except ValueError as exc:
            valid = ", ".join(item.value for item in ObservationKind)
            raise typer.BadParameter(f"kind must be one of: {valid}") from exc

    settings = load_settings()
    store = JanusStore(db or settings.database)
    try:
        rows = store.query_observations_as_of(
            entity,
            stamp,
            kind=observation_kind,
            mode=mode,
            snapshot_id=snapshot,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        f"{len(rows)} observation(s) for {entity} as of {stamp.isoformat()} "
        f"(mode={mode}, snapshot={snapshot or '-'})"
    )
    for row in rows:
        typer.echo(f"- {row.published_at.isoformat()} {row.kind.value} {row.source} {row.value}")


@config_app.command("show")
def config_show(
    config: Optional[Path] = typer.Option(None, "--config", help="Explicit config file"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Show the effective settings with secrets masked."""

    settings = load_settings(config_path=config)
    data = settings.redacted()
    if as_json:
        typer.echo(json.dumps(data, indent=2, sort_keys=True))
    else:
        for key, value in data.items():
            typer.echo(f"{key}: {value}")


@config_app.command("doctor")
def config_doctor(
    config: Optional[Path] = typer.Option(None, "--config", help="Explicit config file"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Check paths, timezone, clock, and provider keys."""

    settings = load_settings(config_path=config)
    checks = settings.doctor()
    if as_json:
        typer.echo(json.dumps([check.__dict__ for check in checks], indent=2, sort_keys=True))
    else:
        for check in checks:
            status = "ok" if check.ok else ("warn" if not check.critical else "FAIL")
            typer.echo(f"[{status}] {check.name}: {check.detail}")
    if any(not check.ok and check.critical for check in checks):
        raise typer.Exit(code=1)


@schema_app.command("export")
def schema_export(
    out: Path = typer.Option(
        Path("schemas/janus.schema.json"), "--out", help="Output path"
    ),
) -> None:
    """Write the current domain contract schema."""

    path = write_schema(out)
    typer.echo(f"wrote {path}")


@schema_app.command("check")
def schema_check(
    path: Path = typer.Option(
        Path("schemas/janus.schema.json"), "--path", help="Schema to verify"
    ),
) -> None:
    """Fail if the checked-in schema differs from the models."""

    ok, detail = check_schema(path)
    typer.echo(detail)
    if not ok:
        raise typer.Exit(code=1)


def _blob_root(root: Optional[Path]) -> Path:
    return Path(root) if root is not None else load_settings().home / "blobs"


@blob_app.command("metrics")
def blob_metrics(
    root: Optional[Path] = typer.Option(None, "--root", help="Blob store root"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Show blob count and bytes on disk."""

    metrics = LocalBlobStore(_blob_root(root)).metrics()
    if as_json:
        typer.echo(json.dumps(metrics, indent=2, sort_keys=True))
    else:
        typer.echo(f"blobs={metrics['blobs']} bytes={metrics['bytes']}")


@blob_app.command("gc")
def blob_gc(
    root: Optional[Path] = typer.Option(None, "--root", help="Blob store root"),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite path"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report without deleting"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Delete blobs that no observation references."""

    settings = load_settings()
    result = LocalBlobStore(_blob_root(root)).gc(
        JanusStore(db or settings.database), dry_run=dry_run
    )
    if as_json:
        typer.echo(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        typer.echo(
            f"scanned={result.scanned} kept={result.kept} "
            f"deleted={result.deleted} bytes_freed={result.bytes_freed}"
        )


def _service(db: Optional[str]):
    from .mcp.service import JanusService

    settings = load_settings()
    return JanusService(JanusStore(db or settings.database))


def _emit_json(payload) -> None:
    typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))


@app.command()
def brief(
    entity: str = typer.Argument(..., help="Entity id, e.g. ACME"),
    as_of: Optional[str] = typer.Option(None, "--as-of", help="Point-in-time timestamp"),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite path"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Show the daily brief for one entity."""

    try:
        payload = _service(db).brief(entity, as_of)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if as_json:
        _emit_json(payload)
        return
    typer.echo(f"brief {entity} as_of={payload['as_of']}")
    typer.echo(
        f"theses={len(payload['theses'])} forecasts={len(payload['forecasts'])} "
        f"observations={len(payload['observations'])}"
    )
    calibration = payload["calibration"]
    typer.echo(
        f"brier={calibration.get('brier')} ece={calibration.get('ece')} "
        f"n={calibration.get('n')}"
    )


@app.command()
def snapshot(
    entity: str = typer.Argument(..., help="Entity id, e.g. ACME"),
    as_of: str = typer.Option(..., "--as-of", help="Point-in-time timestamp"),
    out: Optional[Path] = typer.Option(None, "--out", help="Write snapshot JSON"),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite path"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Create a hash-addressed point-in-time snapshot."""

    try:
        payload = _service(db).snapshot(entity, as_of)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    if as_json or out is None:
        _emit_json(payload)
    else:
        typer.echo(
            f"snapshot {payload['entity_id']} as_of={payload['as_of']} "
            f"count={payload['count']} hash={payload['snapshot_hash']}"
        )


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host"),
    port: int = typer.Option(8766, "--port", help="Bind port"),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite path"),
) -> None:
    """Serve the local JSON API used by the DSH plugin."""

    from .server import make_server

    settings = load_settings()
    server = make_server(
        JanusStore(db or settings.database),
        host=host,
        port=port,
        token=os.environ.get("JANUS_API_TOKEN") or None,
    )
    bound_port = server.server_address[1]
    typer.echo(f"janus api on http://{host}:{bound_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
def _scoped_authorizer(db: Optional[str]):
    from .mcp.auth import authorizer_from_env

    settings = load_settings()
    store = JanusStore(db or settings.database)
    return store, authorizer_from_env(store)


def _emit_auth_error(exc: Exception) -> None:
    from .mcp.auth import AuthorizationError

    if isinstance(exc, AuthorizationError):
        typer.echo(json.dumps({"error": exc.to_dict()}, indent=2, sort_keys=True), err=True)
        raise typer.Exit(code=1)
    raise exc


@mcp_app.command("approve")
def mcp_approve(
    approval_id: str = typer.Argument(..., help="Approval id, e.g. apv-..."),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite path"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Approve one pending MCP write request (requires an admin token)."""

    from .mcp.auth import AuthorizationError

    store, authorizer = _scoped_authorizer(db)
    try:
        approval = authorizer.decide(approval_id, "approve")
    except AuthorizationError as exc:
        _emit_auth_error(exc)
        return
    finally:
        store.close()
    if as_json:
        typer.echo(json.dumps(approval, indent=2, sort_keys=True))
    else:
        typer.echo(f"approved {approval['id']} ({approval['tool']})")


@mcp_app.command("deny")
def mcp_deny(
    approval_id: str = typer.Argument(..., help="Approval id, e.g. apv-..."),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite path"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Deny one pending MCP write request (requires an admin token)."""

    from .mcp.auth import AuthorizationError

    store, authorizer = _scoped_authorizer(db)
    try:
        approval = authorizer.decide(approval_id, "deny")
    except AuthorizationError as exc:
        _emit_auth_error(exc)
        return
    finally:
        store.close()
    if as_json:
        typer.echo(json.dumps(approval, indent=2, sort_keys=True))
    else:
        typer.echo(f"denied {approval['id']} ({approval['tool']})")


@mcp_app.command("approvals")
def mcp_approvals(
    as_of: Optional[str] = typer.Option(None, "--as-of", help="Point-in-time timestamp"),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite path"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """List MCP write approvals, optionally as of a point in time."""

    from .mcp.auth import AuthorizationError

    store, authorizer = _scoped_authorizer(db)
    try:
        stamp = _as_of_option(as_of) if as_of else None
        approvals = authorizer.list_approvals(stamp)
    except AuthorizationError as exc:
        _emit_auth_error(exc)
        return
    finally:
        store.close()
    if as_json:
        typer.echo(json.dumps(approvals, indent=2, sort_keys=True))
    else:
        for approval in approvals:
            typer.echo(
                f"{approval['id']}  {approval['decision']:<8}  "
                f"{approval['tool']}  {approval['caller_id']}  "
                f"expires={approval['expires_at']}"
            )


@mcp_app.command("audit")
def mcp_audit(
    as_of: Optional[str] = typer.Option(None, "--as-of", help="Point-in-time timestamp"),
    limit: Optional[int] = typer.Option(None, "--limit", help="Maximum rows"),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite path"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Show the append-only MCP audit trail."""

    store, authorizer = _scoped_authorizer(db)
    try:
        stamp = _as_of_option(as_of) if as_of else None
        rows = authorizer.audit(stamp, limit)
    finally:
        store.close()
    if as_json:
        typer.echo(json.dumps(rows, indent=2, sort_keys=True))
    else:
        for row in rows:
            typer.echo(
                f"{row['recorded_at']}  {row['decision']:<18}  "
                f"{row['tool']}  {row['caller_id']}  {row['code'] or ''}"
            )


def _as_of_option(value: str) -> datetime:
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter("use an ISO timestamp") from exc
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp


@security_app.command("resolve")
def security_resolve(
    symbol: str = typer.Argument(..., help="Ticker or symbol"),
    as_of: str = typer.Option(..., "--as-of", help="Point-in-time timestamp"),
    exchange: Optional[str] = typer.Option(None, "--exchange", help="Exchange filter"),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite path"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Resolve a symbol as it existed at one time."""

    settings = load_settings()
    security = SecurityMaster(JanusStore(db or settings.database)).resolve(
        symbol, _as_of_option(as_of), exchange=exchange
    )
    if security is None:
        typer.echo(f"security not found: {symbol}", err=True)
        raise typer.Exit(code=1)
    if as_json:
        typer.echo(json.dumps(security.to_dict(), indent=2, sort_keys=True))
    else:
        typer.echo(
            f"{security.id} {security.symbol} entity={security.entity_id} "
            f"exchange={security.exchange or '-'} {security.valid_from.isoformat()}"
        )


@security_app.command("history")
def security_history(
    symbol: str = typer.Argument(..., help="Ticker or symbol"),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite path"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Show every security-master row for a symbol."""

    settings = load_settings()
    rows = SecurityMaster(JanusStore(db or settings.database)).history(symbol)
    payload = [row.to_dict() for row in rows]
    if as_json:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for row in payload:
            typer.echo(
                f"{row['id']} {row['symbol']} {row['valid_from']} -> "
                f"{row['valid_to'] or 'open'}"
            )


@universe_app.command("members")
def universe_members(
    universe: str = typer.Argument(..., help="Universe name, e.g. SPX"),
    as_of: str = typer.Option(..., "--as-of", help="Point-in-time timestamp"),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite path"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Return the members that existed in a universe at one time."""

    settings = load_settings()
    rows = SecurityMaster(JanusStore(db or settings.database)).members(
        universe, _as_of_option(as_of)
    )
    payload = [row.to_dict() for row in rows]
    if as_json:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for row in payload:
            typer.echo(f"{row['symbol']} {row['id']}")


@actions_app.command("list")
def actions_list(
    security_id: Optional[str] = typer.Option(None, "--security", help="Security id"),
    as_of: Optional[str] = typer.Option(None, "--as-of", help="Point-in-time timestamp"),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite path"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """List corporate actions in effective-time order."""

    settings = load_settings()
    stamp = _as_of_option(as_of) if as_of else None
    rows = CorporateActionLedger(JanusStore(db or settings.database)).list(
        security_id, as_of=stamp
    )
    payload = [row.to_dict() for row in rows]
    if as_json:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for row in payload:
            typer.echo(
                f"{row['effective_at']} {row['security_id']} {row['action_type']}"
            )


@actions_app.command("adjust")
def actions_adjust(
    security_id: str = typer.Argument(..., help="Security id"),
    raw_price: float = typer.Option(..., "--price", help="Raw price"),
    as_of: str = typer.Option(..., "--as-of", help="Point-in-time timestamp"),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite path"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Adjust a raw price and print the explicit basis."""

    settings = load_settings()
    payload = CorporateActionLedger(JanusStore(db or settings.database)).adjust_price(
        security_id, raw_price, _as_of_option(as_of)
    )
    if as_json:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        typer.echo(
            f"{security_id} raw={payload['raw_price']} "
            f"adjusted={payload['adjusted_price']:.6f} basis={payload['basis']}"
        )


@spans_app.command("list")
def spans_list(
    observation_id: str = typer.Argument(..., help="Observation id"),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite path"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """List exact source spans for one observation."""

    settings = load_settings()
    rows = SpanStore(JanusStore(db or settings.database)).list(observation_id)
    payload = [row.to_dict() for row in rows]
    if as_json:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    elif not payload:
        typer.echo("no source spans")
    else:
        for row in payload:
            typer.echo(f"{row['id']} {row['locator']} {row['excerpt'][:80]}")


@app.command()
def citation(
    observation_id: str = typer.Argument(..., help="Observation id"),
    span_id: Optional[str] = typer.Option(None, "--span", help="Specific span id"),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite path"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Print a citation backed by an exact source span."""

    settings = load_settings()
    try:
        result = SpanStore(JanusStore(db or settings.database)).citation(
            observation_id, span_id=span_id
        )
    except KeyError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    if as_json:
        typer.echo(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        typer.echo(result.text)
@audit_app.command("verify")
def audit_verify(
    db: Optional[str] = typer.Option(None, "--db", help="SQLite path"),
    checkpoint: Optional[str] = typer.Option(
        None, "--checkpoint", help="Exported audit JSON to compare against"
    ),
    require_complete: bool = typer.Option(
        False,
        "--require-complete",
        help="Also fail when a prediction/outcome has no audit entry",
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Recompute the audit chain and check live rows against it."""

    settings = load_settings()
    chain = AuditChain(JanusStore(db or settings.database))
    try:
        expected = (
            AuditChain.checkpoint_from_file(checkpoint) if checkpoint else None
        )
        report = chain.verify(checkpoint=expected, require_complete=require_complete)
    except AuditError as exc:
        typer.echo(f"audit chain INVALID: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    payload = {
        "status": "ok",
        "count": report.count,
        "head_seq": report.head_seq,
        "head_hash": report.head_hash,
    }
    if as_json:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        typer.echo(
            f"audit chain OK: {report.count} entries, "
            f"head {report.head_hash[:12]}"
        )


@audit_app.command("export")
def audit_export(
    out: Path = typer.Option(..., "--out", help="Destination JSON file"),
    as_of: Optional[str] = typer.Option(None, "--as-of", help="Point-in-time timestamp"),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite path"),
) -> None:
    """Export the chain and its head checkpoint for offline verification."""

    settings = load_settings()
    chain = AuditChain(JanusStore(db or settings.database))
    checkpoint = chain.export(
        out, as_of=_as_of_option(as_of) if as_of else None
    )
    typer.echo(f"exported {checkpoint.count} entries to {out}")


def _retention_rule(value: str) -> RetentionRule:
    parts = value.split(":")
    if len(parts) != 3:
        raise typer.BadParameter("rules use SOURCE:KIND:DAYS, e.g. rss:news:30")
    source, kind, days = parts
    try:
        return RetentionRule(source=source, kind=kind, max_age_days=int(days))
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


@retention_app.command("apply")
def retention_apply(
    as_of: str = typer.Option(..., "--as-of", help="Retention cutoff timestamp"),
    rule: Optional[list[str]] = typer.Option(
        None, "--rule", help="SOURCE:KIND:DAYS (repeatable)"
    ),
    default_days: Optional[int] = typer.Option(
        None, "--default-days", help="Fallback max age for unmatched rows"
    ),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite path"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report without deleting"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Delete observations whose retention window has expired."""

    try:
        stamp = datetime.fromisoformat(as_of)
    except ValueError as exc:
        raise typer.BadParameter("use an ISO timestamp") from exc
    if stamp.tzinfo is None:
        raise typer.BadParameter(
            "--as-of must include a timezone offset, e.g. 2026-02-01T00:00:00+00:00"
        )
    policy = RetentionPolicy(
        rules=tuple(_retention_rule(item) for item in (rule or [])),
        default_max_age_days=default_days,
    )
    settings = load_settings()
    result = apply_retention(
        JanusStore(db or settings.database),
        as_of=stamp,
        policy=policy,
        dry_run=dry_run,
    )
    if as_json:
        typer.echo(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        typer.echo(
            f"scanned={result.scanned} deleted={result.deleted} kept={result.kept}"
        )


@retention_app.command("export")
def retention_export(
    entity: str = typer.Argument(..., help="Entity id"),
    as_of: str = typer.Option(..., "--as-of", help="Point-in-time timestamp"),
    out: Path = typer.Option(..., "--out", help="JSONL output path"),
    field: Optional[list[str]] = typer.Option(
        None, "--field", help="Field name to redact (repeatable)"
    ),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite path"),
) -> None:
    """Export one entity's as-of observations with selected fields redacted."""

    try:
        stamp = datetime.fromisoformat(as_of)
    except ValueError as exc:
        raise typer.BadParameter("use an ISO timestamp") from exc
    if stamp.tzinfo is None:
        raise typer.BadParameter(
            "--as-of must include a timezone offset, e.g. 2026-02-01T00:00:00+00:00"
        )
    settings = load_settings()
    rows = JanusStore(db or settings.database).query_observations_as_of(
        entity, stamp, mode="published"
    )
    target = export_redacted(rows, out, fields=field or [])
    typer.echo(f"wrote {len(rows)} redacted observation(s) to {target}")


@app.command()
def migrate(
    db: Optional[str] = typer.Option(None, "--db", help="SQLite path"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show pending migrations only"),
) -> None:
    """Apply pending schema migrations."""

    settings = load_settings()
    path = db or settings.database
    connection = sqlite3.connect(path)
    try:
        applied = apply_migrations(connection, dry_run=dry_run)
        version = current_version(connection)
    finally:
        connection.close()
    action = "would apply" if dry_run else "applied"
    typer.echo(f"{action}: {applied or 'none'}; current version: {version}")


@model_app.command("list")
def model_list(
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """List stored model artifacts, oldest first."""

    artifacts = ModelRegistry().list()
    if as_json:
        typer.echo(
            json.dumps(
                [_artifact_summary(artifact) for artifact in artifacts],
                indent=2,
                sort_keys=True,
            )
        )
        return
    for artifact in artifacts:
        typer.echo(
            f"{artifact.artifact_id[:12]}  {artifact.version}  "
            f"{artifact.created_at}  {artifact.features_hash[:12]}"
        )


@model_app.command("show")
def model_show(
    ref: str = typer.Argument(
        ..., help="Artifact id, unique id prefix, or exact version"
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Show one stored model artifact."""

    try:
        artifact = ModelRegistry().load(ref)
    except ArtifactNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    except ArtifactCorruptError as exc:
        typer.echo(f"artifact corrupt: {exc.path}", err=True)
        raise typer.Exit(code=1) from exc

    if as_json:
        typer.echo(json.dumps(artifact.to_dict(), indent=2, sort_keys=True))
        return
    typer.echo(f"artifact:      {artifact.artifact_id}")
    typer.echo(f"model:         {artifact.card['name']} {artifact.version}")
    typer.echo(f"created_at:    {artifact.created_at}")
    typer.echo(f"features:      {json.dumps(artifact.features, sort_keys=True)}")
    typer.echo(f"features_hash: {artifact.features_hash}")
    typer.echo(f"data_snapshot: {artifact.data_snapshot or '-'}")
    typer.echo(f"code_version:  {artifact.code_version}")
    typer.echo(f"card:          {json.dumps(artifact.card, sort_keys=True)}")


def _artifact_summary(artifact: ModelArtifact) -> dict[str, object]:
    return {
        "artifact_id": artifact.artifact_id,
        "version": artifact.version,
        "created_at": artifact.created_at,
        "features_hash": artifact.features_hash,
        "model": {
            "name": artifact.card["name"],
            "version": artifact.card["version"],
        },
    }


def main() -> None:
    app()


if __name__ == "__main__":
    main()
