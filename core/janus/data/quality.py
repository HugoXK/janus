from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from ..memory.models import Observation, ObservationKind


@dataclass(frozen=True)
class QualityIssue:
    code: str
    severity: str
    message: str
    observation_id: str


@dataclass(frozen=True)
class QualityReport:
    checked: int
    issues: tuple[QualityIssue, ...]

    @property
    def errors(self) -> tuple[QualityIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> tuple[QualityIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "warning")

    @property
    def ok(self) -> bool:
        return not self.errors


def check_observations(
    observations: list[Observation],
    *,
    as_of: Optional[datetime] = None,
    max_age_days: int = 7,
) -> QualityReport:
    """Fail closed on provenance and price errors; warn on stale feeds."""

    issues: list[QualityIssue] = []
    seen: set[str] = set()
    latest_price: Optional[datetime] = None

    for observation in observations:
        if observation.id in seen:
            issues.append(
                QualityIssue(
                    code="duplicate_id",
                    severity="error",
                    message=f"duplicate observation id {observation.id}",
                    observation_id=observation.id,
                )
            )
        seen.add(observation.id)

        if not observation.source or not observation.raw_hash:
            issues.append(
                QualityIssue(
                    code="missing_provenance",
                    severity="error",
                    message="source or raw_hash is missing",
                    observation_id=observation.id,
                )
            )

        if as_of is not None and observation.published_at > as_of:
            issues.append(
                QualityIssue(
                    code="future_timestamp",
                    severity="error",
                    message="published_at is after the as-of time",
                    observation_id=observation.id,
                )
            )

        if observation.kind is ObservationKind.price:
            if latest_price is None or observation.published_at > latest_price:
                latest_price = observation.published_at
            close = observation.value.get("close")
            try:
                value = float(close)
            except (TypeError, ValueError):
                issues.append(
                    QualityIssue(
                        code="missing_price",
                        severity="warning",
                        message="price observation has no numeric close",
                        observation_id=observation.id,
                    )
                )
                continue
            if value <= 0:
                issues.append(
                    QualityIssue(
                        code="non_positive_price",
                        severity="error",
                        message=f"close is not positive: {value}",
                        observation_id=observation.id,
                    )
                )

    if (
        as_of is not None
        and latest_price is not None
        and latest_price < as_of - timedelta(days=max_age_days)
    ):
        issues.append(
            QualityIssue(
                code="stale_feed",
                severity="warning",
                message=(
                    f"latest price is older than {max_age_days} days "
                    f"({latest_price.isoformat()})"
                ),
                observation_id="",
            )
        )

    return QualityReport(checked=len(observations), issues=tuple(issues))
