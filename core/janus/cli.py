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
from .demo import run_demo
from .forecast.registry import (
    ArtifactCorruptError,
    ArtifactNotFoundError,
    ModelArtifact,
    ModelRegistry,
)
from .memory.migrations import apply_migrations, current_version
from .memory.models import ObservationKind
from .memory.store import JanusStore

app = typer.Typer(
    add_completion=True,
    help="Janus — a market agent with memory and foresight.",
)
config_app = typer.Typer(help="Inspect and validate local configuration.")
schema_app = typer.Typer(help="Export and verify the domain contract schema.")
model_app = typer.Typer(help="Inspect content-addressed model artifacts.")
persona_app = typer.Typer(help="Inspect personas and run calibration tournaments.")
share_app = typer.Typer(help="Approval-first, signed sharing.")
forecast_app = typer.Typer(help="Create, list, and settle forecasts.")
review_app = typer.Typer(help="Debrief and calibration review.")
app.add_typer(config_app, name="config")
app.add_typer(schema_app, name="schema")
app.add_typer(model_app, name="model")
app.add_typer(persona_app, name="persona")
app.add_typer(share_app, name="share")
app.add_typer(forecast_app, name="forecast")
app.add_typer(review_app, name="review")


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
    db: Optional[str] = typer.Option(None, "--db", help="SQLite path (default: from config)"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
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
    if as_json:
        typer.echo(
            json.dumps(
                [row.model_dump(mode="json") for row in rows],
                indent=2,
                sort_keys=True,
                default=str,
            )
        )
        return
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

    parsed: dict[str, float] = {}
    if overrides:
        try:
            parsed = {
                str(key): float(value)
                for key, value in json.loads(overrides).items()
            }
        except (json.JSONDecodeError, AttributeError, TypeError, ValueError) as exc:
            raise typer.BadParameter(
                "overrides must be a JSON object of numbers"
            ) from exc
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
    except (KeyError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    payload = report.to_dict()
    if as_json:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
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


def _share_signer(key_id: str):
    from .share.signing import ShareSigner

    secret = os.environ.get("JANUS_SHARE_SECRET")
    if not secret:
        raise typer.BadParameter("set JANUS_SHARE_SECRET to sign or verify shares")
    return ShareSigner(secret, key_id=key_id)


def _share_service(db: Optional[str], key_id: str):
    from .share.service import ShareService

    settings = load_settings()
    store = JanusStore(db or settings.database)
    return ShareService(store, _share_signer(key_id))


@share_app.command("request")
def share_request(
    kind: str = typer.Option(..., "--kind", help="thesis, forecast, brief, ..."),
    as_of: str = typer.Option(..., "--as-of", help="Point-in-time timestamp"),
    snapshot_hash: str = typer.Option(..., "--snapshot-hash", help="As-of snapshot hash"),
    payload: Optional[str] = typer.Option(None, "--payload", help="JSON payload"),
    payload_file: Optional[Path] = typer.Option(None, "--payload-file", help="JSON file"),
    requested_by: str = typer.Option("local", "--requested-by", help="Requester"),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite path"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Create a pending share request and print its approval card."""

    from .share.service import ShareService

    if (payload is None) == (payload_file is None):
        raise typer.BadParameter("provide exactly one of --payload or --payload-file")
    try:
        if payload is not None:
            body = json.loads(payload)
        else:
            assert payload_file is not None
            body = json.loads(payload_file.read_text())
    except (json.JSONDecodeError, TypeError, OSError) as exc:
        raise typer.BadParameter("payload must be valid JSON") from exc
    settings = load_settings()
    service = ShareService(JanusStore(db or settings.database))
    try:
        request = service.request(
            kind=kind,
            payload=body,
            as_of=as_of,
            snapshot_hash=snapshot_hash,
            requested_by=requested_by,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    card = request.card().to_dict()
    if as_json:
        typer.echo(json.dumps(card, indent=2, sort_keys=True))
        return
    typer.echo(f"request: {card['request_id']} ({card['status']})")
    typer.echo(f"{card['title']} as_of={card['as_of']} snapshot={card['snapshot_hash']}")
    typer.echo(f"payload_hash: {card['payload_hash']}")
    for warning in card["warnings"]:
        typer.echo(f"! {warning}")
    typer.echo(f"approve with: janus share approve {card['request_id']} --approver <name>")


@share_app.command("approve")
def share_approve(
    request_id: str = typer.Argument(..., help="Share request id"),
    approver: str = typer.Option("local", "--approver", help="Approver identity"),
    key_id: str = typer.Option("local", "--key-id", help="Bot-social key id"),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite path"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Approve and sign a pending share request."""

    service = _share_service(db, key_id)
    try:
        request = service.approve(request_id, approver=approver)
    except KeyError as exc:
        raise typer.BadParameter(str(exc)) from exc
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    envelope = request.envelope or {}
    if as_json:
        typer.echo(json.dumps(envelope, indent=2, sort_keys=True))
        return
    typer.echo(f"approved {request.id} by {request.approved_by}")
    typer.echo(f"signature: {envelope.get('signature')}")


@share_app.command("reject")
def share_reject(
    request_id: str = typer.Argument(..., help="Share request id"),
    approver: str = typer.Option("local", "--approver", help="Approver identity"),
    reason: str = typer.Option("", "--reason", help="Rejection reason"),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite path"),
) -> None:
    """Reject a pending share request without signing."""

    from .share.service import ShareService

    settings = load_settings()
    service = ShareService(JanusStore(db or settings.database))
    try:
        request = service.reject(request_id, approver=approver, reason=reason)
    except KeyError as exc:
        raise typer.BadParameter(str(exc)) from exc
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"rejected {request.id} by {request.approved_by}")


@share_app.command("list")
def share_list(
    status: Optional[str] = typer.Option(None, "--status", help="pending, approved, rejected"),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite path"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """List share requests."""

    from .share.service import ShareService

    settings = load_settings()
    service = ShareService(JanusStore(db or settings.database))
    requests = [request.to_dict() for request in service.list(status)]
    if as_json:
        typer.echo(json.dumps(requests, indent=2, sort_keys=True, default=str))
        return
    if not requests:
        typer.echo("no share requests")
        return
    for request in requests:
        typer.echo(
            f"{request['id']} {request['status']} {request['kind']} "
            f"as_of={request['as_of']} by={request['requested_by']}"
        )


@share_app.command("verify")
def share_verify(
    envelope_file: Path = typer.Argument(..., help="Signed share envelope JSON"),
    key_id: str = typer.Option("local", "--key-id", help="Bot-social key id"),
) -> None:
    """Verify a signed share envelope."""

    try:
        envelope = json.loads(envelope_file.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        raise typer.BadParameter("envelope must be valid JSON") from exc
    if _share_signer(key_id).verify(envelope):
        typer.echo("valid signature")
        return
    typer.echo("invalid signature")
    raise typer.Exit(code=1)


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

    parsed_quantiles: Optional[dict[str, float]] = None
    if quantiles:
        try:
            parsed_quantiles = {
                str(key): float(value) for key, value in json.loads(quantiles).items()
            }
        except (json.JSONDecodeError, AttributeError, TypeError, ValueError) as exc:
            raise typer.BadParameter("quantiles must be a JSON object of numbers") from exc
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

    try:
        parsed = {str(key): float(value) for key, value in json.loads(features).items()}
    except (json.JSONDecodeError, AttributeError, TypeError, ValueError) as exc:
        raise typer.BadParameter("features must be a JSON object of numbers") from exc
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
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host"),
    port: int = typer.Option(8766, "--port", help="Bind port"),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite path"),
) -> None:
    """Serve the local JSON API used by the DSH plugin."""

    from .server import make_server

    settings = load_settings()
    server = make_server(
        JanusStore(db or settings.database), host=host, port=port
    )
    bound_port = server.server_address[1]
    typer.echo(f"janus api on http://{host}:{bound_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
