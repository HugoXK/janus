from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable, Optional, Sequence

from ..memory.models import Observation, ObservationKind
from ..memory.store import JanusStore

REVENUE_CONCEPTS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
)
GROSS_PROFIT_CONCEPTS = ("GrossProfit",)
OPERATING_INCOME_CONCEPTS = ("OperatingIncomeLoss",)
NET_INCOME_CONCEPTS = ("NetIncomeLoss", "ProfitLoss")
CFO_CONCEPTS = (
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
)
ASSETS_CONCEPTS = ("Assets",)
LIABILITIES_CONCEPTS = ("Liabilities",)
EQUITY_CONCEPTS = (
    "StockholdersEquity",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
)
DEBT_CONCEPTS = ("LongTermDebt", "LongTermDebtNoncurrent", "DebtCurrent")
EPS_CONCEPTS = ("EarningsPerShareDiluted", "EarningsPerShareBasic")

# Patterns are matched on word boundaries. Ambiguous words (`results`, `probe`,
# `settlement`, `outlook`) only fire with legal/company context, because the
# bare substring misclassifies ordinary text such as "courtesy", "courtyard",
# "probation", "settlement cycle" and "analysts probe the outlook".
EVENT_PATTERNS: dict[str, tuple[str, ...]] = {
    "earnings": (
        r"\bearnings\b",
        r"\b(?:financial|quarterly|annual|full-year|fiscal)\s+results\b",
        r"\b10-q\b",
        r"\b10-k\b",
    ),
    "m&a": (
        r"\bmerger\b",
        r"\bacquisition\b",
        r"\bacquire[sd]?\b",
        r"\bbuyout\b",
    ),
    "litigation": (
        r"\blawsuit\b",
        r"\blitigation\b",
        r"\bcourt\b",
        r"\bclass action\b",
        r"\bsettled\b",
        r"\bsettlement (?:agreement|of)\b",
        r"\b(?:regulatory|government|federal|antitrust|fraud|sec|criminal|doj)\s+probe\b",
        r"\bprobe into\b",
    ),
    "insider": (r"\bform 4\b", r"\binsider\b", r"\bbeneficial ownership\b"),
    "guidance": (
        r"\bguidance\b",
        r"\b(?:company|financial|full-year|fiscal(?:\s+year)?\s+\d{4})\s+outlook\b",
        r"\b(?:raises?|lowers?|cuts?|reaffirms?|withdraws?)\s+(?:its\s+)?outlook\b",
        r"\bforecast\b",
    ),
}

_COMPILED_EVENTS: dict[str, tuple[re.Pattern[str], ...]] = {
    flag: tuple(re.compile(pattern) for pattern in patterns)
    for flag, patterns in EVENT_PATTERNS.items()
}


@dataclass(frozen=True)
class FeatureValue:
    value: float
    concepts: tuple[str, ...]
    observation_ids: tuple[str, ...]


@dataclass(frozen=True)
class FundamentalReport:
    entity_id: str
    as_of: str
    features: dict[str, float]
    provenance: dict[str, list[str]]
    missing: list[str]
    skipped_period: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "as_of": self.as_of,
            "features": dict(sorted(self.features.items())),
            "provenance": {key: sorted(value) for key, value in sorted(self.provenance.items())},
            "missing": sorted(self.missing),
            "skipped_period": sorted(self.skipped_period),
        }


def _parse_date(value: Any) -> Optional[date]:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    # A corrupt feed must yield a missing feature, not a poisoned nan/inf that
    # makes the report non-serialisable.
    return number if math.isfinite(number) else None


def _fact_period(observation: Observation) -> Optional[date]:
    return _parse_date(
        observation.value.get("period_end")
        or observation.value.get("end")
        or observation.valid_from
    )


def _latest_by_period(
    observations: Sequence[Observation], concepts: Iterable[str]
) -> dict[date, Observation]:
    allowed = set(concepts)
    latest: dict[date, Observation] = {}
    for observation in observations:
        concept = str(observation.value.get("concept") or "")
        if concept not in allowed:
            continue
        period = _fact_period(observation)
        if period is None:
            continue
        current = latest.get(period)
        if current is None or (
            observation.published_at,
            observation.id,
        ) > (current.published_at, current.id):
            latest[period] = observation
    return latest


def _latest(
    observations: Sequence[Observation], concepts: Sequence[str]
) -> Optional[Observation]:
    by_period = _latest_by_period(observations, concepts)
    if not by_period:
        return None
    return by_period[max(by_period)]


def _prior_year(
    observations: Sequence[Observation], concepts: Sequence[str], latest: Observation
) -> Optional[Observation]:
    period = _fact_period(latest)
    if period is None:
        return None
    by_period = _latest_by_period(observations, concepts)
    candidates = [
        (abs((period - candidate_date).days - 365), candidate_date)
        for candidate_date in by_period
        if 300 <= (period - candidate_date).days <= 430
    ]
    if not candidates:
        return None
    _, candidate_date = min(candidates)
    return by_period[candidate_date]


def _value(observation: Optional[Observation]) -> Optional[float]:
    if observation is None:
        return None
    return _number(observation.value.get("value"))


def _add(
    features: dict[str, float],
    provenance: dict[str, list[str]],
    name: str,
    value: Optional[float],
    *observations: Optional[Observation],
) -> None:
    if value is None:
        return
    features[name] = float(value)
    provenance[name] = sorted(
        observation.id for observation in observations if observation is not None
    )


def _ratio(
    features: dict[str, float],
    provenance: dict[str, list[str]],
    name: str,
    numerator: Optional[Observation],
    denominator: Optional[Observation],
) -> None:
    top = _value(numerator)
    bottom = _value(denominator)
    if top is None or bottom in (None, 0.0):
        return
    _add(features, provenance, name, top / bottom, numerator, denominator)


def _growth(
    features: dict[str, float],
    provenance: dict[str, list[str]],
    name: str,
    observations: Sequence[Observation],
    concepts: Sequence[str],
) -> None:
    current = _latest(observations, concepts)
    if current is None:
        return
    prior = _prior_year(observations, concepts, current)
    current_value = _value(current)
    prior_value = _value(prior)
    if current_value is None or prior_value in (None, 0.0):
        return
    _add(
        features,
        provenance,
        name,
        current_value / prior_value - 1.0,
        current,
        prior,
    )


def compute_fundamental_features(
    store: JanusStore,
    entity_id: str,
    as_of: datetime,
    *,
    price: Optional[float] = None,
) -> FundamentalReport:
    """Compute filing-backed fundamental features for one as-of date.

    Only facts published at or before ``as_of`` participate. A later
    restatement therefore cannot change a historical feature.
    """

    if as_of.tzinfo is None or as_of.tzinfo.utcoffset(as_of) is None:
        raise ValueError("as_of must be timezone-aware")
    observations: list[Observation] = []
    skipped_period: list[str] = []
    for observation in store.query_observations_as_of(entity_id, as_of, mode="published"):
        if observation.kind is not ObservationKind.fundamental:
            continue
        if observation.published_at > as_of:
            continue
        period = _fact_period(observation)
        if period is None:
            # A period-keyed feature cannot place this fact; surface the drop
            # instead of letting the ``date.max`` fallback hide it.
            skipped_period.append(observation.id)
            continue
        if period <= as_of.date():
            observations.append(observation)

    features: dict[str, float] = {}
    provenance: dict[str, list[str]] = {}

    revenue = _latest(observations, REVENUE_CONCEPTS)
    gross_profit = _latest(observations, GROSS_PROFIT_CONCEPTS)
    operating_income = _latest(observations, OPERATING_INCOME_CONCEPTS)
    net_income = _latest(observations, NET_INCOME_CONCEPTS)
    cfo = _latest(observations, CFO_CONCEPTS)
    assets = _latest(observations, ASSETS_CONCEPTS)
    liabilities = _latest(observations, LIABILITIES_CONCEPTS)
    equity = _latest(observations, EQUITY_CONCEPTS)
    debt = _latest(observations, DEBT_CONCEPTS)
    eps = _latest(observations, EPS_CONCEPTS)

    for name, feature_obs in (
        ("revenue", revenue),
        ("gross_profit", gross_profit),
        ("operating_income", operating_income),
        ("net_income", net_income),
        ("operating_cash_flow", cfo),
        ("assets", assets),
        ("liabilities", liabilities),
        ("equity", equity),
        ("debt", debt),
        ("eps_diluted", eps),
    ):
        _add(features, provenance, name, _value(feature_obs), feature_obs)

    _ratio(features, provenance, "gross_margin", gross_profit, revenue)
    _ratio(features, provenance, "operating_margin", operating_income, revenue)
    _ratio(features, provenance, "net_margin", net_income, revenue)
    _ratio(features, provenance, "cash_flow_margin", cfo, revenue)
    _ratio(features, provenance, "liabilities_to_assets", liabilities, assets)
    _ratio(features, provenance, "debt_to_equity", debt, equity)
    _growth(features, provenance, "revenue_growth_yoy", observations, REVENUE_CONCEPTS)
    _growth(features, provenance, "net_income_growth_yoy", observations, NET_INCOME_CONCEPTS)

    net_income_value = _value(net_income)
    eps_value = _value(eps)
    equity_value = _value(equity)
    if price is not None and eps_value is not None and eps_value > 0:
        # The price is caller-supplied and carries no observation id, so PE
        # provenance lists EPS only; PE is therefore not reproducible from
        # provenance alone (documented in docs/ANALYSIS.md).
        _add(features, provenance, "pe_ratio", float(price) / eps_value, eps)
    if (
        net_income_value not in (None, 0.0)
        and eps_value not in (None, 0.0)
        and equity_value is not None
    ):
        shares = net_income_value / eps_value
        if shares > 0:
            _add(
                features,
                provenance,
                "book_value_per_share",
                equity_value / shares,
                equity,
                net_income,
                eps,
            )

    expected = (
        "revenue",
        "gross_margin",
        "operating_margin",
        "net_margin",
        "cash_flow_margin",
        "liabilities_to_assets",
        "debt_to_equity",
        "revenue_growth_yoy",
        "net_income_growth_yoy",
        "eps_diluted",
    )
    missing = [name for name in expected if name not in features]
    return FundamentalReport(
        entity_id=entity_id,
        as_of=as_of.isoformat(),
        features=dict(sorted(features.items())),
        provenance=provenance,
        missing=missing,
        skipped_period=sorted(skipped_period),
    )


def detect_events(observations: Sequence[Observation]) -> dict[str, list[str]]:
    """Return event flags with the observation ids that support each flag."""

    events: dict[str, set[str]] = {}
    for observation in observations:
        text = " ".join(
            str(observation.value.get(key) or "")
            for key in ("title", "summary", "description", "form", "items")
        ).lower()
        for flag, patterns in _COMPILED_EVENTS.items():
            if any(pattern.search(text) for pattern in patterns):
                events.setdefault(flag, set()).add(observation.id)
    return {
        flag: sorted(ids)
        for flag, ids in sorted(events.items())
    }
