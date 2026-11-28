from __future__ import annotations

import json
import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Iterator, Mapping, Optional

LOGGER_NAME = "janus"
_CORRELATION: ContextVar[dict[str, Any] | None] = ContextVar(
    "janus_correlation", default=None
)
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

_PEM_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)
_URL_USERINFO = re.compile(r"(?i)\b(https?://)([^/\s:@]+):([^/\s@]+)@")
_BEARER_TOKEN = re.compile(r"(?i)\b(Bearer\s+)[A-Za-z0-9._~+/=-]{6,}")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?<![A-Za-z0-9])("
    r"api[_-]?key|apikey|access[_-]?token|auth[_-]?token|refresh[_-]?token|"
    r"client[_-]?secret|private[_-]?key|secret|token|password|passwd"
    r")(\s*[=:]\s*)([^\s&,;\"'<>]+)"
)
_SECRET_SHAPE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\b"
)


def _is_sensitive(key: Any) -> bool:
    text = str(key).lower().replace("-", "_")
    return any(marker in text for marker in _SENSITIVE_MARKERS)


def _scrub_text(text: str) -> str:
    """Mask credential patterns inside free-form text."""

    text = _PEM_PRIVATE_KEY.sub(REDACTED, text)
    text = _URL_USERINFO.sub(lambda match: f"{match.group(1)}{REDACTED}@", text)
    text = _BEARER_TOKEN.sub(lambda match: f"{match.group(1)}{REDACTED}", text)
    text = _SECRET_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{REDACTED}", text
    )
    return _SECRET_SHAPE.sub(REDACTED, text)


def redact(value: Any, *, key: Optional[str] = None) -> Any:
    """Return a copy with likely secrets masked at any depth.

    Free-form strings are scrubbed for credential patterns as well, so a
    provider error carrying ``?api_key=...`` or ``Authorization: Bearer ...``
    is masked even when it is stored under a non-sensitive key.
    """

    if key is not None and _is_sensitive(key):
        return REDACTED
    if isinstance(value, str):
        return _scrub_text(value)
    if isinstance(value, Mapping):
        return {
            str(item_key): redact(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


def current_correlation() -> dict[str, Any]:
    return dict(_CORRELATION.get() or {})


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
            return _scrub_text(base)
        extra = " ".join(
            f"{key}={value}"
            for key, value in redact(structured).items()
            if key != "event"
        )
        event = redact(structured.get("event", record.getMessage()))
        return _scrub_text(f"{base} {event}" + (f" {extra}" if extra else ""))


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
