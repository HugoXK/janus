from __future__ import annotations

from datetime import datetime
from typing import Optional

from .models import Observation, ObservationKind
from .store import JanusStore


def observations_as_of(
    store: JanusStore,
    entity_id: str,
    as_of: datetime,
    kind: Optional[ObservationKind] = None,
) -> list[Observation]:
    """Return only what was knowable at ``as_of``.

    This wrapper exists so callers do not accidentally reach for an
    unrestricted ``SELECT *`` when building a historical view.
    """

    return store.query_observations_as_of(entity_id=entity_id, as_of=as_of, kind=kind)


def assert_no_lookahead(observations: list[Observation], as_of: datetime) -> None:
    """Raise if any observation was published after ``as_of``."""

    for observation in observations:
        if observation.published_at > as_of:
            raise ValueError(
                f"lookahead detected: observation {observation.id} published "
                f"{observation.published_at.isoformat()} > as_of {as_of.isoformat()}"
            )
