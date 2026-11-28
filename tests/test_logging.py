from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

from typer.testing import CliRunner

from janus.cli import app
from janus.data.scheduler import IngestionScheduler
from janus.logging import (
    JsonFormatter,
    TextFormatter,
    configure_logging,
    correlation_scope,
    current_correlation,
    redact,
)
from janus.memory.store import JanusStore

runner = CliRunner()

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


def test_scheduler_emits_correlated_json_fields(caplog) -> None:
    class FailingSource:
        name = "failing"

        def fetch(self, entity_id, start, end):
            raise RuntimeError("boom")

    caplog.set_level(logging.INFO, logger="janus")
    store = JanusStore(":memory:")
    result = IngestionScheduler(store, retries=0).run(
        FailingSource(),
        ["ACME"],
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    records = [record.janus for record in caplog.records if hasattr(record, "janus")]
    events = {record["event"] for record in records}
    assert events == {"ingestion.start", "ingestion.dead_letter", "ingestion.complete"}
    for record in records:
        assert record["run_id"] == result.run_id
        assert record["source"] == "failing"
    dead = next(record for record in records if record["event"] == "ingestion.dead_letter")
    assert dead["entity_id"] == "ACME"
    assert "as_of" in dead
    assert "boom" in dead["error"]


def test_cli_accepts_log_format_and_rejects_bad_values() -> None:
    ok = runner.invoke(app, ["--log-format", "json", "version"])
    assert ok.exit_code == 0, ok.output
    bad = runner.invoke(app, ["--log-format", "xml", "version"])
    assert bad.exit_code != 0


def test_redact_masks_aws_and_live_key_shapes() -> None:
    _FAKE_AWS = "AKIA" + "Q" * 16
    _FAKE_LIVE = "sk_" + "live_" + "z" * 20
    payload = {"aws": _FAKE_AWS, "live": _FAKE_LIVE, "text": f"a {_FAKE_AWS} b {_FAKE_LIVE}"}
    masked = redact(payload)
    assert masked["aws"] == "***"
    assert masked["live"] == "***"
    assert _FAKE_AWS not in masked["text"]
    assert _FAKE_LIVE not in masked["text"]


def test_redact_preserves_container_types() -> None:
    masked = redact({"tuple": ("a", "b"), "list": ["a", "b"]})
    assert masked["tuple"] == ("a", "b")
    assert isinstance(masked["tuple"], tuple)
    assert isinstance(masked["list"], list)


def test_structured_fields_cannot_clobber_the_log_envelope() -> None:
    record = logging.LogRecord("janus.test", logging.INFO, __file__, 1, "hello", (), None)
    record.janus = {"level": "FORGED", "message": "forged", "event": "ingestion.start"}
    payload = json.loads(JsonFormatter().format(record))
    assert payload["level"] == "INFO"
    assert payload["message"] == "hello"
    assert payload["event"] == "ingestion.start"
