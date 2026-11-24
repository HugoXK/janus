from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time as dt_time, timezone
from typing import Any, Callable, Optional

from ..memory.models import Observation, ObservationKind
from .base import DataSource, DataUnavailable

HistoryFetcher = Callable[[str, datetime, datetime], Any]


class YFinanceSource(DataSource):
    """Unofficial Yahoo Finance fallback.

    ``yfinance`` is an optional dependency (``janus-market[data]``). Tests and
    callers can inject a ``history_fetcher`` so the adapter stays usable without
    the package.
    """

    name = "yfinance"

    def __init__(self, history_fetcher: Optional[HistoryFetcher] = None) -> None:
        self._history_fetcher = history_fetcher

    def fetch(self, entity_id: str, start: datetime, end: datetime) -> list[Observation]:
        frame = self._history(entity_id, start, end)
        if frame is None or bool(getattr(frame, "empty", False)):
            return []

        observations: list[Observation] = []
        for index, row in frame.iterrows():
            trading_date = self._date_from_index(index)
            value = {
                "date": trading_date.isoformat(),
                "open": self._number(row.get("Open")),
                "high": self._number(row.get("High")),
                "low": self._number(row.get("Low")),
                "close": self._number(row.get("Close")),
                "adj_close": self._number(row.get("Adj Close")),
                "volume": self._number(row.get("Volume")),
            }
            raw_hash = hashlib.sha256(
                json.dumps(value, sort_keys=True).encode("utf-8")
            ).hexdigest()
            observations.append(
                Observation(
                    id=f"yfinance:price:{entity_id}:{trading_date.isoformat()}",
                    entity_id=entity_id,
                    kind=ObservationKind.price,
                    source=self.name,
                    published_at=datetime.combine(
                        trading_date, dt_time(23, 59, 59), tzinfo=timezone.utc
                    ),
                    observed_at=datetime.now(timezone.utc),
                    value=value,
                    unit="USD",
                    confidence=0.7,
                    raw_hash=raw_hash,
                    raw_uri=f"yfinance:{entity_id}",
                )
            )
        return sorted(observations, key=lambda item: (item.published_at, item.id))

    def _history(self, entity_id: str, start: datetime, end: datetime) -> Any:
        if self._history_fetcher is not None:
            return self._history_fetcher(entity_id, start, end)

        try:
            import yfinance as yf
        except ImportError as exc:
            raise DataUnavailable(
                "yfinance is not installed; install janus-market[data]"
            ) from exc

        ticker = yf.Ticker(entity_id)
        return ticker.history(
            start=start.date(),
            end=(end.date()).isoformat(),
            auto_adjust=False,
        )

    @staticmethod
    def _date_from_index(index: Any) -> date:
        if hasattr(index, "date"):
            value = index.date()
            if isinstance(value, date):
                return value
        return date.fromisoformat(str(index)[:10])

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
