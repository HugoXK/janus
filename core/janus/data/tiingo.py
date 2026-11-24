from __future__ import annotations

import hashlib
import json
import time
from datetime import date, datetime, time as dt_time, timezone
from typing import Any, Optional
from urllib.parse import quote, urlencode

import httpx

from ..memory.models import Observation, ObservationKind
from .base import DataSource, DataUnavailable
from .cache import HttpCache

PRICE_FIELDS = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "adjOpen",
    "adjHigh",
    "adjLow",
    "adjClose",
    "adjVolume",
    "divCash",
    "splitFactor",
)


class TiingoSource(DataSource):
    """Tiingo end-of-day prices.

    Free tier is rate-limited. Set ``TIINGO_API_KEY`` and cache aggressively.
    The EOD response has no publication timestamp, so ``published_at`` is the
    end of the trading day in UTC; that is a conservative point-in-time choice.
    """

    name = "tiingo"
    base_url = "https://api.tiingo.com"

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        client: Optional[httpx.Client] = None,
        cache: Optional[HttpCache] = None,
        min_interval: float = 0.0,
    ) -> None:
        self.api_key = api_key
        self._client = client
        self._owns_client = client is None
        self.cache = cache
        self.min_interval = min_interval
        self._last_request = 0.0

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
            "status": "configured" if self.api_key else "unconfigured",
        }

    def fetch(self, entity_id: str, start: datetime, end: datetime) -> list[Observation]:
        if not self.api_key:
            raise DataUnavailable("TIINGO_API_KEY is not configured")

        url = f"{self.base_url}/tiingo/daily/{quote(entity_id)}/prices"
        params = {
            "startDate": start.date().isoformat(),
            "endDate": end.date().isoformat(),
            "format": "json",
            "resampleFreq": "daily",
        }
        cache_key = f"{url}?{urlencode(sorted(params.items()))}"

        if self.cache is not None:
            cached = self.cache.get(cache_key)
            if cached is not None:
                rows = cached
            else:
                rows = self._request(url, params)
                self.cache.set(cache_key, rows)
        else:
            rows = self._request(url, params)

        if not isinstance(rows, list):
            raise DataUnavailable("Tiingo returned an unexpected payload")

        observations = [self._to_observation(entity_id, row, cache_key) for row in rows]
        return sorted(observations, key=lambda item: (item.published_at, item.id))

    def _wait(self) -> None:
        if self.min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request = time.monotonic()

    def _request(self, url: str, params: dict[str, str]) -> Any:
        headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "application/json",
        }
        last_error = ""
        for attempt in range(3):
            self._wait()
            response = self.client.get(url, params=params, headers=headers)
            if response.status_code == 429 or 500 <= response.status_code < 600:
                last_error = f"HTTP {response.status_code}"
                time.sleep(0.5 * (2**attempt))
                continue
            if response.status_code >= 400:
                raise DataUnavailable(f"Tiingo request failed: HTTP {response.status_code}")
            return response.json()
        raise DataUnavailable(f"Tiingo request failed after retries: {last_error}")

    def _to_observation(self, entity_id: str, row: dict[str, Any], raw_uri: str) -> Observation:
        raw_date = str(row.get("date", ""))[:10]
        try:
            trading_date = date.fromisoformat(raw_date)
        except ValueError as exc:
            raise DataUnavailable(f"Tiingo returned an invalid date: {raw_date!r}") from exc

        published_at = datetime.combine(trading_date, dt_time(23, 59, 59), tzinfo=timezone.utc)
        value = {field: row.get(field) for field in PRICE_FIELDS}
        value["date"] = trading_date.isoformat()
        raw_hash = hashlib.sha256(
            json.dumps(row, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

        return Observation(
            id=f"tiingo:price:{entity_id}:{trading_date.isoformat()}",
            entity_id=entity_id,
            kind=ObservationKind.price,
            source=self.name,
            published_at=published_at,
            observed_at=datetime.now(timezone.utc),
            value=value,
            unit="USD",
            confidence=0.9,
            raw_hash=raw_hash,
            raw_uri=raw_uri,
        )
