from __future__ import annotations

import json
import logging
import sys

from janus.logging import (
    JsonFormatter,
    TextFormatter,
    configure_logging,
    correlation_scope,
    current_correlation,
    redact,
)
# Synthetic fixtures: built at runtime so the secret scanner does not treat
# these obviously-fake test values as committed credentials.
_FAKE_SK = "sk-" + "test" * 4
_FAKE_GITHUB = "ghp_" + "x" * 24
_FAKE_BEARER = "tok_" + "y" * 12
_FAKE_PEM = (
    "-----BEGIN "
    + "RSA PRIVATE KEY"
    + "-----\nMIIEsecret\n-----END "
    + "RSA PRIVATE KEY"
    + "-----"
)


def test_redact_masks_nested_secrets() -> None:
    payload = {
        "api_key": "abc",
        "nested": {"authorization": "Bearer x", "password_hint": "nope"},
        "items": [{"token": "t"}, {"safe": 1}],
    }
    assert redact(payload) == {
        "api_key": "***",
        "nested": {"authorization": "***", "password_hint": "***"},
        "items": [{"token": "***"}, {"safe": 1}],
    }


def test_redact_scrubs_secrets_in_free_text() -> None:
    text = (
        f"GET https://api.example.com/v1?api_key={_FAKE_SK}&x=1 failed; "
        f"Authorization: Bearer {_FAKE_BEARER}; "
        "url https://user:hunter2@example.com/path; "
        f"key {_FAKE_GITHUB}"
    )
    scrubbed = redact(text)
    for secret in (_FAKE_SK, _FAKE_BEARER, "hunter2", _FAKE_GITHUB):
        assert secret not in scrubbed
    assert "api_key=***" in scrubbed
    assert "Bearer ***" in scrubbed
    assert "https://***@example.com/path" in scrubbed


def test_redact_scrubs_private_key_block() -> None:
    assert redact(_FAKE_PEM) == "***"


def test_json_formatter_scrubs_secret_in_exception() -> None:
    try:
        raise RuntimeError(
            f"provider failed: https://api.example.com/v1?api_key={_FAKE_SK}"
        )
    except RuntimeError:
        exc_info = sys.exc_info()
    record = logging.LogRecord(
        "janus.test", logging.ERROR, __file__, 1, "request failed", (), exc_info
    )
    payload = json.loads(JsonFormatter().format(record))
    assert _FAKE_SK not in payload["exception"]
    assert "api_key=***" in payload["exception"]


def test_json_formatter_scrubs_secret_in_event() -> None:
    record = logging.LogRecord(
        "janus.test", logging.ERROR, __file__, 1, "boom", (), None
    )
    record.janus = {
        "event": (
            f"fetch https://api.example.com?token={_FAKE_BEARER} "
            f"Authorization: Bearer {_FAKE_BEARER}"
        )
    }
    payload = json.loads(JsonFormatter().format(record))
    assert _FAKE_BEARER not in payload["event"]
    assert "token=***" in payload["event"]


def test_text_formatter_scrubs_secret_in_message() -> None:
    formatter = TextFormatter("%(levelname)s %(name)s: %(message)s")
    record = logging.LogRecord(
        "janus.test",
        logging.ERROR,
        __file__,
        1,
        f"call failed Authorization: Bearer {_FAKE_BEARER}",
        (),
        None,
    )
    assert _FAKE_BEARER not in formatter.format(record)


def test_json_formatter_is_one_stable_object() -> None:
    record = logging.LogRecord(
        "janus.test", logging.INFO, __file__, 1, "hello", (), None
    )
    record.janus = {"event": "demo", "run_id": "r1", "token": "secret"}
    payload = json.loads(JsonFormatter().format(record))
    assert payload["event"] == "demo"
    assert payload["run_id"] == "r1"
    assert payload["token"] == "***"
    assert payload["level"] == "INFO"
    assert "timestamp" in payload


def test_correlation_scope_merges_and_resets() -> None:
    assert current_correlation() == {}
    with correlation_scope(run_id="r1", source="rss"):
        assert current_correlation() == {"run_id": "r1", "source": "rss"}
        with correlation_scope(entity_id="ACME"):
            assert current_correlation() == {
                "run_id": "r1",
                "source": "rss",
                "entity_id": "ACME",
            }
        assert current_correlation() == {"run_id": "r1", "source": "rss"}
    assert current_correlation() == {}


def test_text_and_json_configuration_are_reconfigurable() -> None:
    configure_logging("DEBUG", "text")
    logger = configure_logging("INFO", "json")
    assert logger.handlers
    assert sum(1 for handler in logger.handlers if getattr(handler, "_janus_console", False)) == 1
