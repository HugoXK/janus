from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from typer.testing import CliRunner

from janus.cli import app
from janus.data.scheduler import IngestionScheduler
from janus.logging import (
    JsonFormatter,
    configure_logging,
    correlation_scope,
    current_correlation,
    log_event,
    redact,
)
from janus.memory.store import JanusStore

runner = CliRunner()


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


def test_text_and_json_configuration_are_reconfigurable() -> None:
    configure_logging("DEBUG", "text")
    logger = configure_logging("INFO", "json")
    assert logger.handlers
    assert sum(1 for handler in logger.handlers if getattr(handler, "_janus_console", False)) == 1
