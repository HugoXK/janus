from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional
from urllib.parse import urlsplit, urlunsplit
from xml.etree import ElementTree

import httpx

from ..memory.models import Observation, ObservationKind
from .base import DataSource, DataUnavailable
from .cache import HttpCache


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, "")
    )


def _child_text(element: ElementTree.Element, names: tuple[str, ...]) -> str:
    for child in element:
        tag = child.tag.split("}")[-1].lower()
        if tag in names:
            return (child.text or "").strip()
    return ""


def _link(element: ElementTree.Element) -> str:
    for child in element:
        tag = child.tag.split("}")[-1].lower()
        if tag == "link":
            text = (child.text or "").strip()
            if text:
                return text
            href = child.attrib.get("href")
            if href:
                return href.strip()
    return ""


def _parse_date(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        stamp = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


class RSSSource(DataSource):
    """RSS 2.0 and Atom ingestion with canonical-URL dedup."""

    name = "rss"

    def __init__(
        self,
        feeds: list[str],
        *,
        client: Optional[httpx.Client] = None,
        cache: Optional[HttpCache] = None,
        min_interval: float = 0.0,
    ) -> None:
        self.feeds = feeds
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
            "status": "configured" if self.feeds else "unconfigured",
        }

    def fetch(self, entity_id: str, start: datetime, end: datetime) -> list[Observation]:
        if not self.feeds:
            raise DataUnavailable("RSSSource requires at least one feed")
        observations: dict[str, Observation] = {}
        for feed in self.feeds:
            text = self._get_text(feed)
            try:
                root = ElementTree.fromstring(text)
            except ElementTree.ParseError as exc:
                raise DataUnavailable(f"invalid RSS/Atom feed: {feed}") from exc
            for item in self._items(root):
                url = _link(item)
                if not url:
                    continue
                canonical = canonical_url(url)
                published_at = _parse_date(
                    _child_text(item, ("pubdate", "published", "updated", "date"))
                )
                if published_at is None or not start <= published_at <= end:
                    continue
                digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
                observation_id = f"rss:{digest[:24]}"
                value = {
                    "title": _child_text(item, ("title",)),
                    "url": canonical,
                    "summary": _child_text(item, ("description", "summary", "content")),
                    "feed": feed,
                    "author": _child_text(item, ("author", "creator")),
                }
                observations[observation_id] = Observation(
                    id=observation_id,
                    entity_id=entity_id,
                    kind=ObservationKind.news,
                    source=self.name,
                    published_at=published_at,
                    observed_at=datetime.now(timezone.utc),
                    value=value,
                    confidence=0.7,
                    raw_hash=hashlib.sha256(
                        json.dumps(value, sort_keys=True).encode("utf-8")
                    ).hexdigest(),
                    raw_uri=canonical,
                )
        return sorted(observations.values(), key=lambda item: (item.published_at, item.id))

    @staticmethod
    def _items(root: ElementTree.Element) -> list[ElementTree.Element]:
        items = [element for element in root.iter() if element.tag.split("}")[-1].lower() == "item"]
        if items:
            return items
        return [
            element for element in root.iter() if element.tag.split("}")[-1].lower() == "entry"
        ]

    def _wait(self) -> None:
        if self.min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request = time.monotonic()

    def _get_text(self, url: str) -> str:
        if self.cache is not None:
            cached = self.cache.get(url)
            if cached is not None:
                return str(cached)
        last_error = ""
        for attempt in range(3):
            self._wait()
            response = self.client.get(url)
            if response.status_code == 429 or 500 <= response.status_code < 600:
                last_error = f"HTTP {response.status_code}"
                time.sleep(0.5 * (2**attempt))
                continue
            if response.status_code >= 400:
                raise DataUnavailable(f"RSS request failed: HTTP {response.status_code}")
            text = response.text
            if self.cache is not None:
                self.cache.set(url, text)
            return text
        raise DataUnavailable(f"RSS request failed after retries: {last_error}")
