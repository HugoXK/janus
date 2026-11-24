from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from janus.data.base import DataUnavailable
from janus.data.blob import LocalBlobStore
from janus.data.sec_edgar import SECEdgarSource
from janus.memory.models import ObservationKind
from janus.memory.store import JanusStore

FIXTURES = Path(__file__).parent / "fixtures"

MSFT_SUBMISSIONS = {
    "cik": "0000789019",
    "name": "Microsoft Corporation",
    "filings": {
        "recent": {
            "accessionNumber": ["0000789019-26-000001"],
            "filingDate": ["2026-01-15"],
            "reportDate": ["2025-12-31"],
            "form": ["10-Q"],
            "primaryDocument": ["msft-20251231.htm"],
            "primaryDocDescription": ["10-Q"],
            "items": [""],
        }
    },
}

MSFT_FACTS = {
    "cik": 789019,
    "entityName": "Microsoft Corporation",
    "facts": {
        "us-gaap": {
            "NetIncomeLoss": {
                "units": {
                    "USD": [
                        {
                            "end": "2025-12-31",
                            "val": 50.0,
                            "fy": 2026,
                            "fp": "Q2",
                            "form": "10-Q",
                            "filed": "2026-01-15",
                            "accn": "0000789019-26-000001",
                            "frame": "CY2025Q4",
                        }
                    ]
                }
            }
        }
    },
}


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _handler(request: httpx.Request) -> httpx.Response:
    assert request.headers["user-agent"] == "janus-test"
    url = str(request.url)
    if "company_tickers.json" in url:
        return httpx.Response(
            200,
            json={"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}},
        )
    if "submissions/CIK0000320193" in url:
        return httpx.Response(200, json=_load("sec_submissions.json"))
    if "companyfacts/CIK0000320193" in url:
        return httpx.Response(200, json=_load("sec_companyfacts.json"))
    if "submissions/CIK0000789019" in url:
        return httpx.Response(200, json=MSFT_SUBMISSIONS)
    if "companyfacts/CIK0000789019" in url:
        return httpx.Response(200, json=MSFT_FACTS)
    return httpx.Response(404)


def _source(tmp_path: Path) -> SECEdgarSource:
    client = httpx.Client(transport=httpx.MockTransport(_handler))
    return SECEdgarSource(
        user_agent="janus-test",
        client=client,
        blob_store=LocalBlobStore(tmp_path / "blobs"),
    )


def test_fetch_filings_and_facts_with_restatement(tmp_path: Path) -> None:
    source = _source(tmp_path)
    rows = source.fetch(
        "0000320193",
        datetime(2025, 10, 1, tzinfo=timezone.utc),
        datetime(2026, 3, 1, tzinfo=timezone.utc),
    )

    filings = [row for row in rows if row.kind is ObservationKind.filing]
    facts = [row for row in rows if row.kind is ObservationKind.fundamental]
    assert len(filings) == 2
    assert len(facts) == 2
    assert {row.value["form"] for row in filings} == {"10-K", "10-Q"}
    assert all(row.source == "sec_edgar" for row in rows)

    revenue = [
        row
        for row in facts
        if row.value["concept"]
        == "RevenueFromContractWithCustomerExcludingAssessedTax"
    ]
    assert {row.value["value"] for row in revenue} == {100.0, 101.0}
    assert len({row.published_at for row in revenue}) == 2
    assert len({row.valid_from for row in revenue}) == 1

    blob_store = LocalBlobStore(tmp_path / "blobs")
    for row in rows:
        assert blob_store.path(row.raw_hash).exists()
        assert blob_store.get(row.raw_hash)


def test_restatement_does_not_overwrite_the_as_filed_fact(tmp_path: Path) -> None:
    source = _source(tmp_path)
    rows = source.fetch(
        "0000320193",
        datetime(2025, 10, 1, tzinfo=timezone.utc),
        datetime(2026, 3, 1, tzinfo=timezone.utc),
    )
    store = JanusStore(":memory:")
    for row in rows:
        store.insert_observation(row)

    before = store.query_observations_as_of(
        "0000320193",
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        kind=ObservationKind.fundamental,
    )
    after = store.query_observations_as_of(
        "0000320193",
        datetime(2026, 3, 1, tzinfo=timezone.utc),
        kind=ObservationKind.fundamental,
    )

    assert {row.value["value"] for row in before} == {100.0}
    assert {row.value["value"] for row in after} == {100.0, 101.0}


def test_ticker_resolution(tmp_path: Path) -> None:
    source = _source(tmp_path)
    rows = source.fetch(
        "AAPL",
        datetime(2025, 10, 1, tzinfo=timezone.utc),
        datetime(2026, 3, 1, tzinfo=timezone.utc),
    )

    assert any(row.kind is ObservationKind.filing for row in rows)


def test_second_company_parses(tmp_path: Path) -> None:
    source = _source(tmp_path)
    rows = source.fetch(
        "0000789019",
        datetime(2025, 10, 1, tzinfo=timezone.utc),
        datetime(2026, 3, 1, tzinfo=timezone.utc),
    )

    assert len([row for row in rows if row.kind is ObservationKind.filing]) == 1
    assert len([row for row in rows if row.kind is ObservationKind.fundamental]) == 1


def test_unknown_ticker_is_explicit(tmp_path: Path) -> None:
    source = _source(tmp_path)
    with pytest.raises(DataUnavailable, match="unknown SEC ticker"):
        source.fetch(
            "NOPE",
            datetime(2025, 10, 1, tzinfo=timezone.utc),
            datetime(2026, 3, 1, tzinfo=timezone.utc),
        )
