from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from ..memory.models import Observation, ObservationKind
from .base import DataSource, DataUnavailable
from .cache import HttpCache


class GDELTSource(DataSource):
    """GDELT DOC 2.0 article ingestion.

    GDELT is a signal, not a truth source: articles are noisy, syndicated, and
    sometimes mis-timestamped. Keep the canonical URL and raw hash.
    """

    name = "gdelt"
    base_url = "https://api.gdeltproject.org/api/v2/doc/doc"

    def __init__(
        self,
        *,
        client: Optional[httpx.Client] = None,
        cache: Optional[HttpCache] = None,
        min_interval: float = 0.0,
    ) -> None:
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
        return {"name": self.name, "status": "configured"}

    def fetch(self, entity_id: str, start: datetime, end: datetime) -> list[Observation]:
        params = {
            "query": entity_id,
            "mode": "artlist",
            "format": "json",
            "maxrecords": "75",
            "startdatetime": start.strftime("%Y%m%d%H%M%S"),
            "enddatetime": end.strftime("%Y%m%d%H%M%S"),
        }
        payload = self._get_json(params)
        articles = payload.get("articles", []) if isinstance(payload, dict) else []
        observations: dict[str, Observation] = {}
        for article in articles:
            if not isinstance(article, dict):
                continue
            url = str(article.get("url") or article.get("url_mobile") or "")
            if not url:
                continue
            try:
                published_at = datetime.strptime(
                    str(article.get("seendate", "")), "%Y%m%dT%H%M%SZ"
                ).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
            observation_id = f"gdelt:{entity_id}:{digest[:24]}"
            if observation_id in observations:
                continue
            value = {
                "title": article.get("title"),
                "url": url,
                "domain": article.get("domain"),
                "language": article.get("language"),
                "sourcecountry": article.get("sourcecountry"),
            }
            observations[observation_id] = Observation(
                id=observation_id,
                entity_id=entity_id,
                kind=ObservationKind.news,
                source=self.name,
                published_at=published_at,
                observed_at=datetime.now(timezone.utc),
                value=value,
                confidence=0.5,
                raw_hash=hashlib.sha256(
                    json.dumps(article, sort_keys=True, default=str).encode("utf-8")
                ).hexdigest(),
                raw_uri=url,
            )
        return sorted(observations.values(), key=lambda item: (item.published_at, item.id))

    def _wait(self) -> None:
        if self.min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request = time.monotonic()

    def _get_json(self, params: dict[str, str]) -> Any:
        key = self.base_url + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        if self.cache is not None:
            cached = self.cache.get(key)
            if cached is not None:
                return cached
        last_error = ""
        for attempt in range(3):
            self._wait()
            response = self.client.get(self.base_url, params=params)
            if response.status_code == 429 or 500 <= response.status_code < 600:
                last_error = f"HTTP {response.status_code}"
                time.sleep(0.5 * (2**attempt))
                continue
            if response.status_code >= 400:
                raise DataUnavailable(f"GDELT request failed: HTTP {response.status_code}")
            try:
                payload = response.json()
            except ValueError as exc:
                raise DataUnavailable("GDELT returned non-JSON") from exc
            if self.cache is not None:
                self.cache.set(key, payload)
            return payload
        raise DataUnavailable(f"GDELT request failed after retries: {last_error}")
