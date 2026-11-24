from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import typer

from . import __version__
from .config import Settings
from .demo import run_demo
from .memory.models import ObservationKind
from .memory.store import JanusStore

app = typer.Typer(
    add_completion=False,
    help="Janus — a market agent with memory and foresight.",
)


@app.command()
def version() -> None:
    """Print the Janus version."""

    typer.echo(__version__)


@app.command()
def demo() -> None:
    """Run the offline end-to-end demonstration."""

    run_demo()


@app.command()
def asof(
    entity: str = typer.Argument(..., help="Entity id, e.g. ACME"),
    when: str = typer.Argument(..., help="ISO timestamp, e.g. 2026-01-15"),
    kind: Optional[str] = typer.Option(None, help="Observation kind filter"),
    db: Optional[str] = typer.Option(None, help="SQLite path (default: ~/.janus/janus.db)"),
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

    settings = Settings()
    store = JanusStore(db or settings.database)
    rows = store.query_observations_as_of(entity, stamp, kind=observation_kind)
    typer.echo(f"{len(rows)} observation(s) for {entity} as of {stamp.isoformat()}")
    for row in rows:
        typer.echo(f"- {row.published_at.isoformat()} {row.kind.value} {row.source} {row.value}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
