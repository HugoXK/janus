from __future__ import annotations

import json
import math
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
from .memory.encryption_cli import keys_app
from .memory.provenance import ProvenanceError, ProvenanceTracer
from .memory.security_master import SecurityMaster
from .memory.spans import SpanStore
from .memory.snapshot_archive import export_snapshot, import_snapshot, verify_snapshot
from .memory.store import JanusStore


app = typer.Typer(
    add_completion=False,
    help="Janus — a market agent with memory and foresight.",
)
config_app = typer.Typer(help="Inspect and validate local configuration.")
schema_app = typer.Typer(help="Export and verify the domain contract schema.")
model_app = typer.Typer(help="Inspect content-addressed model artifacts.")
persona_app = typer.Typer(help="Inspect personas and run calibration tournaments.")
forecast_app = typer.Typer(help="Create, list, and settle forecasts.")
review_app = typer.Typer(help="Debrief and calibration review.")
app.add_typer(config_app, name="config")
app.add_typer(schema_app, name="schema")
app.add_typer(model_app, name="model")
app.add_typer(persona_app, name="persona")
app.add_typer(forecast_app, name="forecast")
app.add_typer(review_app, name="review")
blob_app = typer.Typer(help="Inspect and garbage-collect content-addressed blobs.")
security_app = typer.Typer(help="Resolve point-in-time securities.")
universe_app = typer.Typer(help="Query point-in-time universe membership.")
actions_app = typer.Typer(help="Inspect corporate actions and price adjustments.")
spans_app = typer.Typer(help="Inspect exact source spans and citations.")
retention_app = typer.Typer(help="Apply retention and export redacted data.")
mcp_app = typer.Typer(help="Inspect scoped MCP approvals and audit records.")
audit_app = typer.Typer(help="Verify and export the tamper-evident audit chain.")
app.add_typer(blob_app, name="blob")
app.add_typer(security_app, name="security")
app.add_typer(universe_app, name="universe")
app.add_typer(actions_app, name="actions")
app.add_typer(keys_app, name="keys")
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

    load_settings()
    store = _open_store(db)
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

    load_settings()
    result = LocalBlobStore(_blob_root(root)).gc(
        _open_store(db), dry_run=dry_run
    )
    if as_json:
        typer.echo(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        typer.echo(
            f"scanned={result.scanned} kept={result.kept} "
            f"deleted={result.deleted} bytes_freed={result.bytes_freed}"
        )


def _open_store(db: Optional[str]) -> JanusStore:
    from .memory.encryption import EncryptionError
    from .memory.store import open_store

    settings = load_settings()
    try:
        return open_store(db or settings.database)
    except EncryptionError as exc:
        typer.echo(f"error [{exc.code}]: {exc}", err=True)
        raise typer.Exit(code=1) from exc


def _service(db: Optional[str]):
    from .mcp.service import JanusService

    return JanusService(_open_store(db))


def _emit_json(payload) -> None:
    """Emit strict JSON; non-finite numbers are an error, not a bare token."""

    try:
        text = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise typer.BadParameter(f"output is not strict JSON: {exc}") from exc
    typer.echo(text)


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite number: {value}")


def _parse_number_map(raw: str, label: str) -> dict[str, float]:
    try:
        parsed = json.loads(raw, parse_constant=_reject_constant)
        values = {str(key): float(value) for key, value in parsed.items()}
    except (json.JSONDecodeError, AttributeError, TypeError, ValueError) as exc:
        raise typer.BadParameter(f"{label} must be a JSON object of finite numbers") from exc
    if any(not math.isfinite(value) for value in values.values()):
        raise typer.BadParameter(f"{label} must be a JSON object of finite numbers")
    return values


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

    load_settings()
    server = make_server(
        _open_store(db),
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

    load_settings()
    store = _open_store(db)
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

    load_settings()
    security = SecurityMaster(_open_store(db)).resolve(
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

    load_settings()
    rows = SecurityMaster(_open_store(db)).history(symbol)
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

    load_settings()
    rows = SecurityMaster(_open_store(db)).members(
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

    load_settings()
    stamp = _as_of_option(as_of) if as_of else None
    rows = CorporateActionLedger(_open_store(db)).list(
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

    load_settings()
    payload = CorporateActionLedger(_open_store(db)).adjust_price(
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

    load_settings()
    rows = SpanStore(_open_store(db)).list(observation_id)
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

    load_settings()
    try:
        result = SpanStore(_open_store(db)).citation(
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

    load_settings()
    chain = AuditChain(_open_store(db))
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

    load_settings()
    chain = AuditChain(_open_store(db))
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
    load_settings()
    result = apply_retention(
        _open_store(db),
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
    load_settings()
    rows = _open_store(db).query_observations_as_of(
        entity, stamp, mode="published"
    )
    target = export_redacted(rows, out, fields=field or [])
    typer.echo(f"wrote {len(rows)} redacted observation(s) to {target}")


@forecast_app.command("list")
def forecast_list(
    thesis_id: Optional[str] = typer.Option(None, "--thesis-id", help="Filter by thesis"),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite path"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """List recorded forecasts."""

    payload = _service(db).list_forecasts(thesis_id)
    if as_json:
        _emit_json(payload)
        return
    if not payload:
        typer.echo("no forecasts")
        return
    for row in payload:
        typer.echo(
            f"{row['id']} {row['target']} p={row['probability']} "
            f"as_of={row['as_of']} model={row['model_version']}"
        )


@forecast_app.command("create")
def forecast_create(
    thesis_id: str = typer.Option(..., "--thesis-id", help="Thesis id"),
    target: str = typer.Option("direction", "--target", help="Forecast target"),
    horizon: str = typer.Option("1M", "--horizon", help="Forecast horizon"),
    probability: float = typer.Option(..., "--probability", help="P(up), 0..1"),
    model_version: str = typer.Option(..., "--model-version", help="Model version"),
    features_hash: str = typer.Option(..., "--features-hash", help="Feature vector hash"),
    as_of: str = typer.Option(..., "--as-of", help="Point-in-time timestamp"),
    quantiles: Optional[str] = typer.Option(None, "--quantiles", help="JSON quantiles"),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite path"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Record a forecast before its outcome exists."""

    parsed_quantiles = _parse_number_map(quantiles, "--quantiles") if quantiles else None
    try:
        payload = _service(db).create_forecast(
            thesis_id=thesis_id,
            target=target,
            horizon=horizon,
            as_of=as_of,
            probability=probability,
            model_version=model_version,
            features_hash=features_hash,
            quantiles=parsed_quantiles,
        )
    except (KeyError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    if as_json:
        _emit_json(payload)
    else:
        typer.echo(f"forecast {payload['id']} p={payload['probability']}")


@forecast_app.command("settle")
def forecast_settle(
    prediction_id: str = typer.Argument(..., help="Prediction id"),
    start_price: float = typer.Option(..., "--start-price", help="Start price"),
    end_price: float = typer.Option(..., "--end-price", help="End price"),
    realized_at: str = typer.Option(..., "--realized-at", help="Outcome timestamp"),
    source: str = typer.Option("cli", "--source", help="Outcome source"),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite path"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Settle a P(up) forecast against a price pair."""

    for label, price in (("--start-price", start_price), ("--end-price", end_price)):
        if not math.isfinite(price) or price <= 0:
            raise typer.BadParameter(f"{label} must be a finite positive number")
    try:
        payload = _service(db).settle_forecast(
            prediction_id=prediction_id,
            start_price=start_price,
            end_price=end_price,
            realized_at=realized_at,
            source=source,
        )
    except (KeyError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    if as_json:
        _emit_json(payload)
    else:
        typer.echo(f"settled {prediction_id} score={payload['score']}")


@review_app.command("debrief")
def review_debrief(
    prediction_id: str = typer.Argument(..., help="Prediction id"),
    features: str = typer.Option(..., "--features", help="JSON feature object"),
    regime: Optional[str] = typer.Option(None, "--regime", help="Regime label"),
    calibration: Optional[float] = typer.Option(None, "--calibration", help="Calibration score"),
    lessons: str = typer.Option("", "--lessons", help="Lessons learned"),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite path"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Record a debrief for a settled prediction."""

    parsed = _parse_number_map(features, "--features")
    if calibration is not None and (
        not math.isfinite(calibration) or not 0.0 <= calibration <= 1.0
    ):
        raise typer.BadParameter("--calibration must be a finite number in [0, 1]")
    try:
        payload = _service(db).debrief(
            prediction_id=prediction_id,
            features=parsed,
            regime=regime,
            calibration=calibration,
            lessons=lessons,
        )
    except (KeyError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    if as_json:
        _emit_json(payload)
    else:
        typer.echo(f"review {payload['id']} for {prediction_id}")


@review_app.command("calibration")
def review_calibration(
    db: Optional[str] = typer.Option(None, "--db", help="SQLite path"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Show the calibration report over settled predictions."""

    payload = _service(db).calibrate()
    if as_json:
        _emit_json(payload)
        return
    typer.echo(
        f"n={payload.get('n')} brier={payload.get('brier')} "
        f"ece={payload.get('ece')} log_loss={payload.get('log_loss')}"
    )


@app.command()
def provenance(
    observation_id: str = typer.Argument(..., help="Observation id"),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite path"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Resolve an observation id to its citation and source span."""

    load_settings()
    tracer = ProvenanceTracer(_open_store(db))
    try:
        traced = tracer.require(observation_id)
    except ProvenanceError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    if as_json:
        typer.echo(
            json.dumps(traced.to_dict(), indent=2, sort_keys=True, default=str)
        )
    else:
        typer.echo(traced.citation)


@app.command()
def counterfactual(
    prediction_id: str = typer.Argument(..., help="Prediction id to replay"),
    remove: Optional[list[str]] = typer.Option(
        None, "--remove", help="Evidence observation id to exclude (repeatable)"
    ),
    persona: Optional[str] = typer.Option(
        None, "--persona", help="Counterfactual persona id"
    ),
    overrides: Optional[str] = typer.Option(
        None, "--overrides", help="JSON feature overrides, e.g. '{\"rsi_14\": 30}'"
    ),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite path"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Replay a decision with swapped evidence or persona."""

    from .review.counterfactual import CounterfactualReplay

    parsed = _parse_number_map(overrides, "overrides") if overrides else {}
    settings = load_settings()
    store = JanusStore(db or settings.database)
    try:
        report = CounterfactualReplay(store).replay(
            prediction_id,
            remove_evidence=remove or [],
            persona_id=persona,
            feature_overrides=parsed,
        )
    except KeyError as exc:
        raise typer.BadParameter(str(exc)) from exc
    payload = report.to_dict()
    if as_json:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    typer.echo(
        f"{payload['prediction_id']} as_of={payload['as_of']} "
        f"delta={payload['delta']:+.3f}"
    )
    typer.echo(
        f"original: {payload['original']['probability']:.3f} "
        f"({payload['original']['reasoning']})"
    )
    typer.echo(
        f"counterfactual: {payload['counterfactual']['probability']:.3f} "
        f"({payload['counterfactual']['reasoning']})"
    )
    typer.echo(payload["explanation"])


@persona_app.command("list")
def persona_list(
    db: Optional[str] = typer.Option(None, "--db", help="SQLite path"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """List stored personas and their weights."""

    settings = load_settings()
    store = JanusStore(db or settings.database)
    personas = [
        {
            "id": persona.id,
            "name": persona.name,
            "version": persona.version,
            "weights": persona.weights,
        }
        for persona in store.list_personas()
    ]
    if as_json:
        typer.echo(json.dumps(personas, indent=2, sort_keys=True))
    elif not personas:
        typer.echo("no personas")
    else:
        for persona in personas:
            typer.echo(f"{persona['id']} {persona['name']} ({persona['version']})")


@persona_app.command("tournament")
def persona_tournament(
    scenarios: Path = typer.Argument(..., help="Tournament scenario JSON"),
    seed: int = typer.Option(7, "--seed", help="Bootstrap seed"),
    bootstrap: int = typer.Option(1000, "--bootstrap", help="Bootstrap resamples"),
    confidence: float = typer.Option(0.95, "--confidence", help="Interval confidence"),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite path"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Compare every stored persona on the same fixed scenario set."""

    from .persona.tournament import PersonaTournament

    settings = load_settings()
    store = JanusStore(db or settings.database)
    try:
        report = PersonaTournament.load(scenarios).run(
            store.list_personas(),
            seed=seed,
            bootstrap=bootstrap,
            confidence=confidence,
        )
    except (KeyError, ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    payload = report.to_dict()
    if as_json:
        try:
            typer.echo(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False))
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        return
    typer.echo(
        f"{payload['n_scenarios']} scenarios, {len(payload['personas'])} personas, "
        f"seed={payload['seed']}, bootstrap={payload['bootstrap']}"
    )
    for result in payload["personas"]:
        drawdown = (
            f"{result['max_drawdown']:.3f}"
            if result["max_drawdown"] is not None
            else "-"
        )
        typer.echo(
            f"{result['name']}: brier={result['brier']:.3f} "
            f"[{result['brier_ci'][0]:.3f}, {result['brier_ci'][1]:.3f}] "
            f"hit={result['hit_rate']:.3f} drawdown={drawdown}"
        )


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

archive_app = typer.Typer(help="Export, import, and verify as-of snapshot archives.")
app.add_typer(archive_app, name="archive")


@archive_app.command("export")
def archive_export(
    out: Path = typer.Option(..., "--out", help="Archive directory"),
    as_of: str = typer.Option(..., "--as-of", help="Snapshot as-of timestamp"),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite path"),
    no_parquet: bool = typer.Option(False, "--no-parquet", help="Skip Parquet files"),
    as_json: bool = typer.Option(False, "--json", help="Emit manifest JSON"),
) -> None:
    """Write a hash-manifested as-of snapshot archive."""

    try:
        stamp = datetime.fromisoformat(as_of)
    except ValueError as exc:
        raise typer.BadParameter("use an ISO timestamp") from exc
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    load_settings()
    try:
        manifest = export_snapshot(
            _open_store(db),
            out,
            as_of=stamp,
            parquet=not no_parquet,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if as_json:
        typer.echo(json.dumps(manifest, indent=2, sort_keys=True))
    else:
        typer.echo(
            f"wrote {out} observations={manifest['counts']['observations']} "
            f"features={manifest['counts']['features']} "
            f"hash={manifest['snapshot_hash'][:12]}"
        )


@archive_app.command("verify")
def archive_verify(
    directory: Path = typer.Argument(..., help="Archive directory"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Verify an archive manifest and every referenced file."""

    result = verify_snapshot(directory)
    if as_json:
        typer.echo(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    elif result.ok:
        typer.echo(f"ok snapshot={result.snapshot_hash[:12]}")
    else:
        for error in result.errors:
            typer.echo(error, err=True)
    if not result.ok:
        raise typer.Exit(code=1)


@archive_app.command("import")
def archive_import(
    directory: Path = typer.Argument(..., help="Archive directory"),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite path"),
    skip_verify: bool = typer.Option(False, "--skip-verify", help="Skip manifest checks"),
) -> None:
    """Import a verified archive into a store."""

    load_settings()
    try:
        counts = import_snapshot(
            _open_store(db), directory, verify=not skip_verify
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        f"imported observations={counts['observations']} features={counts['features']}"
    )

