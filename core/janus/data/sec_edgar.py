from __future__ import annotations

import hashlib
import json
import time
from datetime import date, datetime, time as dt_time, timezone
from typing import Any, Optional

import httpx

from ..memory.models import Observation, ObservationKind
from .base import DataSource, DataUnavailable
from .blob import LocalBlobStore
from .cache import HttpCache

FORM_TYPES = {"10-K", "10-Q"}

DEFAULT_CONCEPTS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "NetIncomeLoss",
    "EarningsPerShareDiluted",
    "Assets",
    "Liabilities",
    "CashAndCashEquivalentsAtCarryingValue",
    "OperatingIncomeLoss",
    "GrossProfit",
)


class SECEdgarSource(DataSource):
    """SEC EDGAR submissions and XBRL company facts.

    SEC data is authoritative and free. It is also rate-limited: set a
    descriptive ``User-Agent`` and keep requests below 10 per second. The
    adapter stores raw JSON documents in a content-addressed blob store and
    keeps every as-filed fact, so a later restatement does not overwrite the
    original.
    """

    name = "sec_edgar"
    base_url = "https://data.sec.gov"
    ticker_url = "https://www.sec.gov/files/company_tickers.json"
    default_user_agent = (
        "Janus/0.1 (+https://github.com/HugoXK/janus; hugo2001xk@gmail.com)"
    )

    def __init__(
        self,
        user_agent: Optional[str] = None,
        *,
        client: Optional[httpx.Client] = None,
        cache: Optional[HttpCache] = None,
        blob_store: Optional[LocalBlobStore] = None,
        min_interval: float = 0.11,
        concepts: Optional[tuple[str, ...]] = None,
    ) -> None:
        self.user_agent = user_agent or self.default_user_agent
        self._client = client
        self._owns_client = client is None
        self.cache = cache
        self.blob_store = blob_store
        self.min_interval = min_interval
        self.concepts = concepts or DEFAULT_CONCEPTS
        self._last_request = 0.0
        self._ticker_map: Optional[dict[str, str]] = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=30.0)
        return self._client

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()

    def health(self) -> dict[str, str]:
        return {
            "name": self.name,
            "status": "configured" if self.user_agent else "unconfigured",
        }

    def fetch(self, entity_id: str, start: datetime, end: datetime) -> list[Observation]:
        cik = self._resolve_cik(entity_id)
        start_date = start.date()
        end_date = end.date()
        observations: dict[str, Observation] = {}

        submissions = self._get_json(f"{self.base_url}/submissions/CIK{cik}.json")
        submissions_hash = self._store_blob(
            json.dumps(submissions, sort_keys=True).encode("utf-8")
        )
        for filing in self._iter_filings(submissions, cik, start_date, end_date):
            observation = self._filing_observation(
                cik, filing, submissions_hash, observations
            )
            observations[observation.id] = observation

        facts_payload = self._get_json(
            f"{self.base_url}/api/xbrl/companyfacts/CIK{cik}.json"
        )
        facts_hash = self._store_blob(
            json.dumps(facts_payload, sort_keys=True).encode("utf-8")
        )
        for fact in self._iter_facts(facts_payload, cik, start_date, end_date):
            observation = self._fact_observation(cik, fact, facts_hash)
            observations[observation.id] = observation

        return sorted(observations.values(), key=lambda item: (item.published_at, item.id))

    # ------------------------------------------------------------------
    # Filings
    # ------------------------------------------------------------------
    def _iter_filings(
        self,
        submissions: dict[str, Any],
        cik: str,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        recent = submissions.get("filings", {}).get("recent", {})
        accessions = recent.get("accessionNumber", [])
        filing_dates = recent.get("filingDate", [])
        forms = recent.get("form", [])
        primary_documents = recent.get("primaryDocument", [])
        descriptions = recent.get("primaryDocDescription", [])
        report_dates = recent.get("reportDate", [])
        items_list = recent.get("items", [])

        count = min(
            len(accessions),
            len(filing_dates),
            len(forms),
        )
        filings: list[dict[str, Any]] = []
        for index in range(count):
            form = str(forms[index])
            if form not in FORM_TYPES:
                continue
            try:
                filed = date.fromisoformat(str(filing_dates[index]))
            except ValueError:
                continue
            if not start_date <= filed <= end_date:
                continue
            filings.append(
                {
                    "cik": cik,
                    "accession": str(accessions[index]),
                    "form": form,
                    "filing_date": filed.isoformat(),
                    "report_date": self._at(report_dates, index),
                    "primary_document": self._at(primary_documents, index),
                    "description": self._at(descriptions, index),
                    "items": self._at(items_list, index),
                }
            )
        return filings

    def _filing_observation(
        self,
        cik: str,
        filing: dict[str, Any],
        submissions_hash: str,
        _seen: dict[str, Observation],
    ) -> Observation:
        raw_hash = self._store_blob(
            json.dumps(filing, sort_keys=True).encode("utf-8")
        )
        accession = str(filing["accession"])
        primary_document = str(filing.get("primary_document") or "")
        raw_uri = (
            f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
            f"{accession.replace('-', '')}/{primary_document}"
        )
        published_at = datetime.combine(
            date.fromisoformat(str(filing["filing_date"])),
            dt_time(23, 59, 59),
            tzinfo=timezone.utc,
        )
        return Observation(
            id=f"sec:filing:{cik}:{accession}",
            entity_id=cik,
            kind=ObservationKind.filing,
            source=self.name,
            published_at=published_at,
            observed_at=datetime.now(timezone.utc),
            value={**filing, "submissions_hash": submissions_hash},
            confidence=1.0,
            raw_hash=raw_hash,
            raw_uri=raw_uri,
        )

    # ------------------------------------------------------------------
    # XBRL facts
    # ------------------------------------------------------------------
    def _iter_facts(
        self,
        payload: dict[str, Any],
        cik: str,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        us_gaap = payload.get("facts", {}).get("us-gaap", {})
        facts: list[dict[str, Any]] = []
        for concept in self.concepts:
            concept_data = us_gaap.get(concept)
            if not isinstance(concept_data, dict):
                continue
            units = concept_data.get("units", {})
            for unit, entries in units.items():
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    filed = entry.get("filed")
                    period_end = entry.get("end")
                    if not filed or not period_end:
                        continue
                    try:
                        filed_date = date.fromisoformat(str(filed))
                        period_end_date = date.fromisoformat(str(period_end))
                    except ValueError:
                        continue
                    if not start_date <= filed_date <= end_date:
                        continue
                    facts.append(
                        {
                            "concept": concept,
                            "unit": unit,
                            "value": entry.get("val"),
                            "period_end": period_end_date.isoformat(),
                            "filed": filed_date.isoformat(),
                            "fy": entry.get("fy"),
                            "fp": entry.get("fp"),
                            "form": entry.get("form"),
                            "accn": entry.get("accn"),
                            "frame": entry.get("frame"),
                        }
                    )
        return facts

    def _fact_observation(
        self,
        cik: str,
        fact: dict[str, Any],
        facts_hash: str,
    ) -> Observation:
        raw_hash = self._store_blob(
            json.dumps(fact, sort_keys=True).encode("utf-8")
        )
        key = "|".join(
            str(fact.get(name, ""))
            for name in ("concept", "unit", "accn", "period_end", "value", "filed")
        )
        fact_id = "sec:xbrl:" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
        published_at = datetime.combine(
            date.fromisoformat(str(fact["filed"])),
            dt_time(23, 59, 59),
            tzinfo=timezone.utc,
        )
        valid_from = datetime.combine(
            date.fromisoformat(str(fact["period_end"])),
            dt_time(0, 0, 0),
            tzinfo=timezone.utc,
        )
        return Observation(
            id=fact_id,
            entity_id=cik,
            kind=ObservationKind.fundamental,
            source=self.name,
            published_at=published_at,
            observed_at=datetime.now(timezone.utc),
            valid_from=valid_from,
            value={**fact, "companyfacts_hash": facts_hash},
            unit=str(fact.get("unit") or "") or None,
            confidence=1.0,
            raw_hash=raw_hash,
            raw_uri=f"{self.base_url}/api/xbrl/companyfacts/CIK{cik}.json",
        )

    # ------------------------------------------------------------------
    # Networking
    # ------------------------------------------------------------------
    def _wait(self) -> None:
        if self.min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request = time.monotonic()

    def _get_json(self, url: str) -> Any:
        if self.cache is not None:
            cached = self.cache.get(url)
            if cached is not None:
                return cached

        headers = {
            "User-Agent": self.user_agent,
            "Accept-Encoding": "gzip, deflate",
        }
        last_error = ""
        for attempt in range(3):
            self._wait()
            response = self.client.get(url, headers=headers)
            if response.status_code == 429 or 500 <= response.status_code < 600:
                last_error = f"HTTP {response.status_code}"
                time.sleep(0.5 * (2**attempt))
                continue
            if response.status_code >= 400:
                raise DataUnavailable(f"SEC request failed: HTTP {response.status_code}")
            payload = response.json()
            if self.cache is not None:
                self.cache.set(url, payload)
            return payload
        raise DataUnavailable(f"SEC request failed after retries: {last_error}")

    def _resolve_cik(self, entity_id: str) -> str:
        if entity_id.isdigit():
            return entity_id.zfill(10)

        if self._ticker_map is None:
            payload = self._get_json(self.ticker_url)
            self._ticker_map = {
                str(item.get("ticker", "")).upper(): str(item.get("cik_str", "")).zfill(10)
                for item in payload.values()
                if isinstance(item, dict)
            }
        ticker = entity_id.upper()
        if ticker not in self._ticker_map:
            raise DataUnavailable(f"unknown SEC ticker: {entity_id}")
        return self._ticker_map[ticker]

    def _store_blob(self, data: bytes) -> str:
        if self.blob_store is not None:
            return self.blob_store.put(data)
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def _at(values: list[Any], index: int) -> str:
        return str(values[index]) if index < len(values) else ""
