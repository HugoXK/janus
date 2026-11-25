from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Iterator, Mapping, Optional

LOGGER_NAME = "janus"
_CORRELATION: ContextVar[dict[str, Any]] = ContextVar("janus_correlation", default={})
_SENSITIVE_MARKERS = (
    "secret",
    "token",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "private_key",
)
REDACTED = "***"


def _is_sensitive(key: Any) -> bool:
    text = str(key).lower().replace("-", "_")
    return any(marker in text for marker in _SENSITIVE_MARKERS)


def redact(value: Any, *, key: Optional[str] = None) -> Any:
    """Return a copy with likely secrets masked at any depth."""

    if key is not None and _is_sensitive(key):
        return REDACTED
    if isinstance(value, Mapping):
        return {
            str(item_key): redact(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


def current_correlation() -> dict[str, Any]:
    return dict(_CORRELATION.get())


@contextmanager
def correlation_scope(**fields: Any) -> Iterator[dict[str, Any]]:
    """Merge correlation fields for the duration of a block."""

    merged = {**current_correlation(), **{key: value for key, value in fields.items() if value is not None}}
    token = _CORRELATION.set(merged)
    try:
        yield merged
    finally:
        _CORRELATION.reset(token)


class JsonFormatter(logging.Formatter):
    """One JSON object per line with stable keys and redacted fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        structured = getattr(record, "janus", None)
        if isinstance(structured, Mapping):
            payload.update(structured)
        else:
            payload["event"] = record.getMessage()
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(redact(payload), sort_keys=True, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        structured = getattr(record, "janus", None)
        if not isinstance(structured, Mapping):
            return base
        extra = " ".join(
            f"{key}={value}"
            for key, value in redact(structured).items()
            if key != "event"
        )
        event = structured.get("event", record.getMessage())
        return f"{base} {event}" + (f" {extra}" if extra else "")


def configure_logging(
    level: str = "INFO", log_format: str = "text"
) -> logging.Logger:
    """Configure the ``janus`` logger once with JSON or text output."""

    normalized = str(level).upper()
    if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError(f"invalid log level: {level}")
    normalized_format = str(log_format).lower()
    if normalized_format not in {"text", "json"}:
        raise ValueError(f"invalid log format: {log_format}")

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(normalized)
    logger.propagate = True
    for existing in list(logger.handlers):
        if getattr(existing, "_janus_console", False):
            logger.removeHandler(existing)
    handler = logging.StreamHandler()
    handler._janus_console = True  # type: ignore[attr-defined]
    handler.setLevel(normalized)
    if normalized_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(TextFormatter("%(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    return logger


def log_event(
    event: str,
    *,
    level: int = logging.INFO,
    logger: Optional[logging.Logger] = None,
    **fields: Any,
) -> None:
    payload = {
        "event": event,
        **current_correlation(),
        **fields,
    }
    target = logger or logging.getLogger(LOGGER_NAME)
    target.log(level, event, extra={"janus": redact(payload)})
