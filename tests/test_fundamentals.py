from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from janus.analysis.fundamentals import (
    compute_fundamental_features,
    detect_events,
)
from janus.memory.models import Observation, ObservationKind
from janus.memory.store import JanusStore


def _filed(value: date) -> datetime:
    return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)


def _fact(
    obs_id: str,
    concept: str,
    value: float,
    period_end: str,
    filed: str,
    *,
    entity_id: str = "ACME",
) -> Observation:
    return Observation(
        id=obs_id,
        entity_id=entity_id,
        kind=ObservationKind.fundamental,
        source="sec_edgar",
        published_at=_filed(date.fromisoformat(filed)),
        valid_from=_filed(date.fromisoformat(period_end)),
        value={
            "concept": concept,
            "value": value,
            "period_end": period_end,
            "filed": filed,
            "accn": obs_id,
        },
        raw_hash=f"hash:{obs_id}",
    )


def _seed(store: JanusStore) -> None:
    facts = [
        ("rev-2025", "RevenueFromContractWithCustomerExcludingAssessedTax", 100.0, "2025-12-31", "2026-01-15"),
        ("rev-2024", "RevenueFromContractWithCustomerExcludingAssessedTax", 80.0, "2024-12-31", "2025-01-15"),
        ("gp-2025", "GrossProfit", 40.0, "2025-12-31", "2026-01-15"),
        ("op-2025", "OperatingIncomeLoss", 25.0, "2025-12-31", "2026-01-15"),
        ("ni-2025", "NetIncomeLoss", 20.0, "2025-12-31", "2026-01-15"),
        ("ni-2024", "NetIncomeLoss", 10.0, "2024-12-31", "2025-01-15"),
        ("cfo-2025", "NetCashProvidedByUsedInOperatingActivities", 30.0, "2025-12-31", "2026-01-15"),
        ("assets-2025", "Assets", 200.0, "2025-12-31", "2026-01-15"),
        ("liab-2025", "Liabilities", 100.0, "2025-12-31", "2026-01-15"),
        ("equity-2025", "StockholdersEquity", 100.0, "2025-12-31", "2026-01-15"),
        ("debt-2025", "LongTermDebt", 20.0, "2025-12-31", "2026-01-15"),
        ("eps-2025", "EarningsPerShareDiluted", 2.0, "2025-12-31", "2026-01-15"),
    ]
    for fact in facts:
        store.insert_observation(_fact(*fact))


def test_computes_fixture_ratios_with_provenance() -> None:
    store = JanusStore(":memory:")
    _seed(store)
    report = compute_fundamental_features(
        store, "ACME", datetime(2026, 2, 1, tzinfo=timezone.utc), price=40.0
    )

    assert report.features["revenue"] == 100.0
    assert report.features["gross_margin"] == pytest.approx(0.4)
    assert report.features["operating_margin"] == pytest.approx(0.25)
    assert report.features["net_margin"] == pytest.approx(0.2)
    assert report.features["cash_flow_margin"] == pytest.approx(0.3)
    assert report.features["liabilities_to_assets"] == pytest.approx(0.5)
    assert report.features["debt_to_equity"] == pytest.approx(0.2)
    assert report.features["revenue_growth_yoy"] == pytest.approx(0.25)
    assert report.features["net_income_growth_yoy"] == pytest.approx(1.0)
    assert report.features["pe_ratio"] == pytest.approx(20.0)
    assert report.features["book_value_per_share"] == pytest.approx(10.0)
    assert report.provenance["net_margin"] == ["ni-2025", "rev-2025"]
    assert report.missing == []


def test_restatement_does_not_leak_backwards() -> None:
    store = JanusStore(":memory:")
    _seed(store)
    store.insert_observation(
        _fact(
            "rev-restated",
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            120.0,
            "2025-12-31",
            "2026-02-15",
        )
    )

    before = compute_fundamental_features(
        store, "ACME", datetime(2026, 2, 1, tzinfo=timezone.utc)
    )
    after = compute_fundamental_features(
        store, "ACME", datetime(2026, 3, 1, tzinfo=timezone.utc)
    )

    assert before.features["revenue"] == 100.0
    assert before.provenance["revenue"] == ["rev-2025"]
    assert after.features["revenue"] == 120.0
    assert after.provenance["revenue"] == ["rev-restated"]
    assert after.features["revenue_growth_yoy"] == pytest.approx(0.5)


def test_missing_facts_are_explicit() -> None:
    store = JanusStore(":memory:")
    store.insert_observation(
        _fact("rev", "Revenues", 10.0, "2025-12-31", "2026-01-15")
    )
    report = compute_fundamental_features(
        store, "ACME", datetime(2026, 2, 1, tzinfo=timezone.utc)
    )
    assert report.features["revenue"] == 10.0
    assert "net_margin" in report.missing
    assert "revenue_growth_yoy" in report.missing


def test_as_of_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        compute_fundamental_features(
            JanusStore(":memory:"), "ACME", datetime(2026, 1, 1)
        )


def test_event_flags_carry_observation_ids() -> None:
    def event(obs_id: str, title: str, form: str = "") -> Observation:
        return Observation(
            id=obs_id,
            entity_id="ACME",
            kind=ObservationKind.news,
            source="rss",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            value={"title": title, "form": form},
            raw_hash=obs_id,
        )

    events = detect_events(
        [
            event("earn", "ACME reports quarterly results", "10-Q"),
            event("deal", "ACME announces acquisition of BETA"),
            event("suit", "ACME faces a lawsuit"),
            event("insider", "Form 4 insider filing"),
            event("guide", "ACME raises guidance"),
            event("none", "A regular product update"),
        ]
    )
    assert events["earnings"] == ["earn"]
    assert events["m&a"] == ["deal"]
    assert events["litigation"] == ["suit"]
    assert events["insider"] == ["insider"]
    assert events["guidance"] == ["guide"]
    assert "none" not in {item for ids in events.values() for item in ids}


def _news(obs_id: str, title: str, form: str = "") -> Observation:
    return Observation(
        id=obs_id,
        entity_id="ACME",
        kind=ObservationKind.news,
        source="rss",
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        value={"title": title, "form": form},
        raw_hash=obs_id,
    )


def test_event_flags_ignore_near_miss_text() -> None:
    events = detect_events(
        [
            _news("courtesy", "A courtesy update for shareholders"),
            _news("courtyard", "The courtyard renovation is complete"),
            _news("probation", "The probation period ends in May"),
            _news("cycle", "Settlement cycle shortens to T+1"),
            _news("probe", "Analysts probe the outlook for margins"),
            _news("results", "Management discussed the results"),
        ]
    )
    assert events == {}


def test_event_flags_require_legal_or_company_context() -> None:
    events = detect_events(
        [
            _news("legal", "ACME discloses a regulatory probe and a settlement agreement"),
            _news("earn", "ACME reports quarterly financial results", "10-Q"),
            _news("guide", "ACME raises its outlook for the fiscal year"),
        ]
    )
    assert events["litigation"] == ["legal"]
    assert events["earnings"] == ["earn"]
    assert events["guidance"] == ["guide"]


def test_non_finite_fact_values_are_treated_as_missing() -> None:
    import json

    store = JanusStore(":memory:")
    store.insert_observation(_fact("rev-nan", "Revenues", float("nan"), "2025-12-31", "2026-01-15"))
    store.insert_observation(_fact("rev-inf", "Revenues", float("inf"), "2025-06-30", "2025-07-15"))
    report = compute_fundamental_features(
        store, "ACME", datetime(2026, 2, 1, tzinfo=timezone.utc)
    )
    assert "revenue" not in report.features
    # The report must stay strictly JSON-serialisable even with a corrupt feed.
    json.dumps(report.to_dict(), allow_nan=False)


def test_period_guard_excludes_later_periods_and_reports_periodless_facts() -> None:
    store = JanusStore(":memory:")
    store.insert_observation(
        _fact("rev-future", "Revenues", 999.0, "2026-06-30", "2026-01-15")
    )
    store.insert_observation(
        Observation(
            id="rev-no-period",
            entity_id="ACME",
            kind=ObservationKind.fundamental,
            source="sec_edgar",
            published_at=_filed(date(2026, 1, 15)),
            valid_from=None,
            value={"concept": "Revenues", "value": 5.0},
            raw_hash="hash:no-period",
        )
    )
    report = compute_fundamental_features(
        store, "ACME", datetime(2026, 2, 1, tzinfo=timezone.utc)
    )
    assert "revenue" not in report.features
    assert report.skipped_period == ["rev-no-period"]
    assert report.to_dict()["skipped_period"] == ["rev-no-period"]
