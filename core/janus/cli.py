from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer

from . import __version__
from .config import load_settings
from .contracts import SCHEMA_VERSION, check_schema, write_schema
from .demo import run_demo
from .forecast.registry import (
    ArtifactCorruptError,
    ArtifactNotFoundError,
    ModelArtifact,
    ModelRegistry,
)
from .memory.migrations import apply_migrations, current_version
from .memory.models import ObservationKind
from .memory.security_master import SecurityMaster
from .memory.store import JanusStore

app = typer.Typer(
    add_completion=False,
    help="Janus — a market agent with memory and foresight.",
)
config_app = typer.Typer(help="Inspect and validate local configuration.")
schema_app = typer.Typer(help="Export and verify the domain contract schema.")
model_app = typer.Typer(help="Inspect content-addressed model artifacts.")
security_app = typer.Typer(help="Resolve point-in-time securities.")
universe_app = typer.Typer(help="Query point-in-time universe membership.")
app.add_typer(config_app, name="config")
app.add_typer(schema_app, name="schema")
app.add_typer(model_app, name="model")
app.add_typer(security_app, name="security")
app.add_typer(universe_app, name="universe")


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
