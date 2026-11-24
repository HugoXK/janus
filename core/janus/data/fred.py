from __future__ import annotations

import hashlib
import json
import time
from datetime import date, datetime, time as dt_time, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from ..memory.models import Observation, ObservationKind
from .base import DataSource, DataUnavailable
from .cache import HttpCache


class FREDSource(DataSource):
    """FRED observations with ALFRED vintage support.

    Set ``FRED_API_KEY``. Without a vintage, ``published_at`` is the day after
    the observation date (a conservative estimate, because FRED does not expose
    a publication timestamp). With ``vintage="YYYY-MM-DD"``, the vintage date is
    the publication time and the value is the one known on that date.
    """

    name = "fred"
    base_url = "https://api.stlouisfed.org/fred"

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        vintage: Optional[str] = None,
        client: Optional[httpx.Client] = None,
        cache: Optional[HttpCache] = None,
        min_interval: float = 0.0,
    ) -> None:
        self.api_key = api_key
        self.vintage = vintage
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
            raise DataUnavailable("FRED_API_KEY is not configured")

        series_url = f"{self.base_url}/series?" + urlencode(
            {"series_id": entity_id, "api_key": self.api_key, "file_type": "json"}
        )
        params = {
            "series_id": entity_id,
            "api_key": self.api_key,
            "file_type": "json",
            "observation_start": start.date().isoformat(),
            "observation_end": end.date().isoformat(),
        }
        if self.vintage is not None:
            params["realtime_start"] = self.vintage
            params["realtime_end"] = self.vintage
        observations_url = f"{self.base_url}/series/observations?" + urlencode(params)
        public_params = {key: value for key, value in params.items() if key != "api_key"}
        public_url = f"{self.base_url}/series/observations?" + urlencode(public_params)

        series = self._get_json(series_url)
        payload = self._get_json(observations_url)
        unit = None
        seriess = series.get("seriess", []) if isinstance(series, dict) else []
        if seriess:
            unit = seriess[0].get("units")

        result: list[Observation] = []
        for entry in payload.get("observations", []):
            raw_value = entry.get("value")
            if raw_value in (None, "."):
                continue
            try:
                observation_date = date.fromisoformat(str(entry["date"]))
                value = float(raw_value)
            except (KeyError, TypeError, ValueError):
                continue

            if self.vintage is not None:
                try:
                    vintage_date = date.fromisoformat(self.vintage)
                except ValueError as exc:
                    raise DataUnavailable(f"invalid FRED vintage: {self.vintage}") from exc
                published_at = datetime.combine(
                    vintage_date, dt_time(23, 59, 59), tzinfo=timezone.utc
                )
                version = self.vintage
            else:
                published_at = datetime.combine(
                    observation_date + timedelta(days=1),
                    dt_time(23, 59, 59),
                    tzinfo=timezone.utc,
                )
                version = "latest"

            value_dict = {
                "series_id": entity_id,
                "date": observation_date.isoformat(),
                "value": value,
                "realtime_start": entry.get("realtime_start"),
                "realtime_end": entry.get("realtime_end"),
                "vintage": self.vintage,
            }
            raw_hash = hashlib.sha256(
                json.dumps(value_dict, sort_keys=True).encode("utf-8")
            ).hexdigest()
            result.append(
                Observation(
                    id=f"fred:{entity_id}:{observation_date.isoformat()}:{version}",
                    entity_id=entity_id,
                    kind=ObservationKind.macro,
                    source=self.name,
                    published_at=published_at,
                    observed_at=datetime.now(timezone.utc),
                    valid_from=datetime.combine(
                        observation_date, dt_time(0, 0, 0), tzinfo=timezone.utc
                    ),
                    value=value_dict,
                    unit=str(unit) if unit else None,
                    confidence=1.0,
                    raw_hash=raw_hash,
                    raw_uri=public_url,
                )
            )
        return sorted(result, key=lambda item: (item.published_at, item.id))

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

        last_error = ""
        for attempt in range(3):
            self._wait()
            response = self.client.get(url)
            if response.status_code == 429 or 500 <= response.status_code < 600:
                last_error = f"HTTP {response.status_code}"
                time.sleep(0.5 * (2**attempt))
                continue
            if response.status_code >= 400:
                raise DataUnavailable(f"FRED request failed: HTTP {response.status_code}")
            payload = response.json()
            if self.cache is not None:
                self.cache.set(url, payload)
            return payload
        raise DataUnavailable(f"FRED request failed after retries: {last_error}")
