from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from janus.memory.models import Observation, ObservationKind
from janus.memory.retention import (
    RetentionPolicy,
    RetentionRule,
    apply_retention,
    export_redacted,
    redact_observation,
    redact_value,
)
from janus.memory.store import JanusStore


def _obs(
    obs_id: str,
    *,
    source: str = "rss",
    kind: ObservationKind = ObservationKind.news,
    published_at: datetime | None = None,
    value: dict | None = None,
) -> Observation:
    return Observation(
        id=obs_id,
        entity_id="ACME",
        kind=kind,
        source=source,
        published_at=published_at or datetime(2026, 1, 1, tzinfo=timezone.utc),
        value=value or {"title": obs_id},
        raw_hash=f"hash:{obs_id}",
    )


def test_rule_matches_source_prefix_and_kind() -> None:
    rule = RetentionRule(source="rss", kind="news", max_age_days=30)
    assert rule.matches(_obs("a", source="rss:ir")) is True
    assert rule.matches(_obs("a", source="gdelt")) is False
    assert rule.matches(_obs("a", kind=ObservationKind.price)) is False


def test_apply_retention_deletes_only_expired() -> None:
    store = JanusStore(":memory:")
    as_of = datetime(2026, 2, 1, tzinfo=timezone.utc)
    store.insert_observation(_obs("old", published_at=as_of - timedelta(days=45)))
    store.insert_observation(_obs("new", published_at=as_of - timedelta(days=5)))
    store.insert_observation(
        _obs(
            "price",
            source="tiingo",
            kind=ObservationKind.price,
            published_at=as_of - timedelta(days=45),
        )
    )
    policy = RetentionPolicy(
        rules=(
            RetentionRule(source="rss", kind="news", max_age_days=30),
            RetentionRule(source="tiingo", kind="price", max_age_days=3650),
        )
    )

    result = apply_retention(store, as_of=as_of, policy=policy)

    assert result.scanned == 3
    assert result.deleted == 1
    assert result.kept == 2
    assert result.deleted_ids == ("old",)
    assert result.by_source == {"rss": 1}
    assert store.get_observation("old") is None
    assert store.get_observation("new") is not None
    assert store.get_observation("price") is not None


def test_dry_run_reports_without_deleting() -> None:
    store = JanusStore(":memory:")
    as_of = datetime(2026, 2, 1, tzinfo=timezone.utc)
    store.insert_observation(_obs("old", published_at=as_of - timedelta(days=45)))
    policy = RetentionPolicy(rules=(RetentionRule(max_age_days=30),))

    result = apply_retention(store, as_of=as_of, policy=policy, dry_run=True)

    assert result.deleted == 1
    assert store.get_observation("old") is not None


def test_default_policy_keeps_unmatched_sources() -> None:
    store = JanusStore(":memory:")
    as_of = datetime(2026, 2, 1, tzinfo=timezone.utc)
    store.insert_observation(_obs("rss", published_at=as_of - timedelta(days=45)))
    store.insert_observation(
        _obs("sec", source="sec_edgar", published_at=as_of - timedelta(days=45))
    )
    policy = RetentionPolicy(
        rules=(RetentionRule(source="rss", max_age_days=30),),
        default_max_age_days=None,
    )

    result = apply_retention(store, as_of=as_of, policy=policy)

    assert result.deleted_ids == ("rss",)
    assert store.get_observation("sec") is not None


def test_policy_round_trips() -> None:
    policy = RetentionPolicy(
        rules=(RetentionRule(source="rss", kind="news", max_age_days=30),),
        default_max_age_days=365,
    )
    assert RetentionPolicy.from_dict(policy.to_dict()) == policy


def test_as_of_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        apply_retention(
            JanusStore(":memory:"),
            as_of=datetime(2026, 1, 1),
            policy=RetentionPolicy(),
        )


def test_redaction_is_deep_and_does_not_mutate() -> None:
    value = {
        "email": "a@example.com",
        "profile": {"phone": "123", "safe": "ok"},
        "list": [{"ssn": "x"}],
    }
    redacted = redact_value(value, {"email", "phone", "ssn"})
    assert redacted == {
        "email": "***",
        "profile": {"phone": "***", "safe": "ok"},
        "list": [{"ssn": "***"}],
    }
    assert value["email"] == "a@example.com"


def test_redact_observation_and_export(tmp_path) -> None:
    observation = _obs(
        "news",
        value={"title": "hello", "email": "a@example.com"},
    )
    payload = redact_observation(observation, {"email"})
    assert payload["value"]["email"] == "***"
    assert observation.value["email"] == "a@example.com"

    out = export_redacted([observation], tmp_path / "redacted.jsonl", fields={"email"})
    line = json.loads(out.read_text().strip())
    assert line["value"]["email"] == "***"
    assert line["id"] == "news"


def test_retention_cli_apply_and_export(tmp_path, monkeypatch) -> None:
    from typer.testing import CliRunner

    from janus.cli import app

    path = tmp_path / "janus.db"
    store = JanusStore(path)
    as_of = datetime(2026, 2, 1, tzinfo=timezone.utc)
    store.insert_observation(
        _obs(
            "old",
            published_at=as_of - timedelta(days=45),
            value={"title": "hello", "email": "a@example.com"},
        )
    )
    store.insert_observation(_obs("new", published_at=as_of - timedelta(days=2)))
    monkeypatch.setenv("JANUS_DB", str(path))
    runner = CliRunner()

    applied = runner.invoke(
        app,
        [
            "retention",
            "apply",
            "--as-of",
            as_of.isoformat(),
            "--rule",
            "rss:news:30",
            "--json",
        ],
    )
    assert applied.exit_code == 0, applied.output
    assert json.loads(applied.output)["deleted"] == 1
    assert store.get_observation("old") is None

    # fresh row for the export path
    store.insert_observation(
        _obs(
            "export",
            published_at=as_of - timedelta(days=1),
            value={"title": "hello", "email": "a@example.com"},
        )
    )
    out = tmp_path / "redacted.jsonl"
    exported = runner.invoke(
        app,
        [
            "retention",
            "export",
            "ACME",
            "--as-of",
            as_of.isoformat(),
            "--out",
            str(out),
            "--field",
            "email",
        ],
    )
    assert exported.exit_code == 0, exported.output
    payloads = [json.loads(line) for line in out.read_text().splitlines()]
    assert all(item["value"].get("email") in (None, "***") for item in payloads)


def test_redact_observation_covers_top_level_fields() -> None:
    observation = Observation(
        id="top",
        entity_id="ACME",
        kind=ObservationKind.news,
        source="rss",
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        value={"title": "hello"},
        raw_hash="hash:top",
        raw_uri="s3://bucket/secret",
    )

    payload = redact_observation(observation, {"raw_uri", "source", "raw_hash"})
    assert payload["raw_uri"] == "***"
    assert payload["source"] == "***"
    assert payload["raw_hash"] == "***"
    assert payload["value"]["title"] == "hello"
    assert observation.raw_uri == "s3://bucket/secret"


def test_redact_observation_unknown_field_is_a_noop() -> None:
    observation = _obs("nope")
    payload = redact_observation(observation, {"does_not_exist"})
    assert payload["source"] == "rss"
    assert payload["raw_hash"] == "hash:nope"
    assert payload["value"]["title"] == "nope"


def test_dry_run_sets_the_flag() -> None:
    store = JanusStore(":memory:")
    as_of = datetime(2026, 2, 1, tzinfo=timezone.utc)
    store.insert_observation(_obs("old", published_at=as_of - timedelta(days=45)))
    policy = RetentionPolicy(rules=(RetentionRule(max_age_days=30),))

    rehearsal = apply_retention(store, as_of=as_of, policy=policy, dry_run=True)
    assert rehearsal.dry_run is True
    assert rehearsal.deleted == 1

    real = apply_retention(store, as_of=as_of, policy=policy)
    assert real.dry_run is False
    assert real.deleted == 1


def test_first_matching_rule_wins() -> None:
    observation = _obs("x", source="rss:reuters")
    broad = RetentionPolicy(
        rules=(
            RetentionRule(source="*", kind="*", max_age_days=365),
            RetentionRule(source="rss", kind="news", max_age_days=30),
        )
    )
    specific_first = RetentionPolicy(
        rules=(
            RetentionRule(source="rss", kind="news", max_age_days=30),
            RetentionRule(source="*", kind="*", max_age_days=365),
        )
    )
    assert broad.max_age_for(observation) == 365
    assert specific_first.max_age_for(observation) == 30


def test_retention_cli_rejects_naive_as_of(tmp_path, monkeypatch) -> None:
    from typer.testing import CliRunner

    from janus.cli import app

    path = tmp_path / "janus.db"
    JanusStore(path).close()
    monkeypatch.setenv("JANUS_DB", str(path))
    runner = CliRunner()

    applied = runner.invoke(
        app, ["retention", "apply", "--as-of", "2026-02-01T00:00:00"]
    )
    assert applied.exit_code != 0
    assert "timezone offset" in applied.output
    exported = runner.invoke(
        app,
        [
            "retention",
            "export",
            "ACME",
            "--as-of",
            "2026-02-01T00:00:00",
            "--out",
            str(tmp_path / "out.jsonl"),
        ],
    )
    assert exported.exit_code != 0
    assert "timezone offset" in exported.output
