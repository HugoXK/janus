from __future__ import annotations

from datetime import datetime, timedelta, timezone

from janus.data.quality import check_observations
from janus.memory.models import Observation, ObservationKind


def _observation(
    obs_id: str = "px-1",
    *,
    entity_id: str = "ACME",
    close: float = 100.0,
    published_at: datetime | None = None,
) -> Observation:
    return Observation(
        id=obs_id,
        entity_id=entity_id,
        kind=ObservationKind.price,
        source="test",
        published_at=published_at or datetime(2026, 1, 1, tzinfo=timezone.utc),
        value={"close": close},
        raw_hash=f"hash:{obs_id}",
    )


def test_valid_observation_has_no_errors() -> None:
    report = check_observations(
        [_observation()],
        as_of=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    assert report.ok
    assert report.errors == ()


def test_duplicate_and_non_positive_price_are_errors() -> None:
    report = check_observations(
        [_observation("dup", close=-1), _observation("dup", close=10)],
        as_of=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    codes = {issue.code for issue in report.errors}
    assert "duplicate_id" in codes
    assert "non_positive_price" in codes


def test_future_timestamp_is_an_error() -> None:
    future = _observation(
        "future", published_at=datetime(2026, 1, 10, tzinfo=timezone.utc)
    )
    report = check_observations(
        [future], as_of=datetime(2026, 1, 5, tzinfo=timezone.utc)
    )
    assert any(issue.code == "future_timestamp" for issue in report.errors)


def test_stale_feed_is_a_warning() -> None:
    stale = _observation(
        "stale", published_at=datetime(2025, 12, 1, tzinfo=timezone.utc)
    )
    report = check_observations(
        [stale],
        as_of=datetime(2026, 1, 5, tzinfo=timezone.utc),
        max_age_days=7,
    )
    assert any(issue.code == "stale_feed" for issue in report.warnings)


def test_stale_feed_is_per_entity() -> None:
    fresh = _observation(
        "fresh",
        entity_id="FRESH",
        published_at=datetime(2026, 1, 4, tzinfo=timezone.utc),
    )
    stale = _observation(
        "stale",
        entity_id="STALE",
        published_at=datetime(2025, 12, 1, tzinfo=timezone.utc),
    )
    report = check_observations(
        [fresh, stale],
        as_of=datetime(2026, 1, 5, tzinfo=timezone.utc),
        max_age_days=7,
    )
    stale_ids = {issue.observation_id for issue in report.warnings if issue.code == "stale_feed"}
    assert stale_ids == {"STALE"}


def test_issues_carry_source_and_entity() -> None:
    report = check_observations([_observation("bad", close=-1)])
    issue = next(item for item in report.errors if item.code == "non_positive_price")
    assert issue.source == "test"
    assert issue.entity_id == "ACME"


def test_quality_cli_json(tmp_path, monkeypatch) -> None:
    import json

    from typer.testing import CliRunner

    from janus.cli import app
    from janus.memory.store import JanusStore

    path = tmp_path / "janus.db"
    store = JanusStore(path)
    store.insert_observation(_observation("bad", close=-1))
    monkeypatch.setenv("JANUS_DB", str(path))
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["quality", "ACME", "--as-of", "2026-01-02T00:00:00+00:00", "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["checked"] == 1
    assert "non_positive_price" in {issue["code"] for issue in payload["errors"]}


def test_quality_report_samples_the_newest_rows_and_reports_truncation() -> None:
    from janus.mcp.service import JanusService
    from janus.memory.store import JanusStore

    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    store = JanusStore(":memory:")
    for index in range(600):
        store.insert_observation(
            _observation(
                f"p{index}",
                close=100.0 + index * 0.01,
                published_at=start + timedelta(days=index),
            )
        )
    as_of = start + timedelta(days=599)
    service = JanusService(store)

    sampled = service.quality_report("ACME", as_of)
    assert sampled["truncated"] is True
    assert sampled["checked"] == 500
    assert sampled["window"]["to"] == as_of.isoformat()
    assert sampled["window"]["from"] == (start + timedelta(days=100)).isoformat()
    assert [issue["code"] for issue in sampled["warnings"]] == []

    full = service.quality_report("ACME", as_of, limit=None)
    assert full["truncated"] is False
    assert full["checked"] == 600


def test_quality_report_exposes_the_staleness_threshold() -> None:
    from janus.mcp.service import JanusService
    from janus.memory.store import JanusStore

    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    store = JanusStore(":memory:")
    store.insert_observation(_observation("old", published_at=start))
    service = JanusService(store)
    as_of = start + timedelta(days=30)

    strict = service.quality_report("ACME", as_of, max_age_days=7)
    assert [issue["code"] for issue in strict["warnings"]] == ["stale_feed"]
    relaxed = service.quality_report("ACME", as_of, max_age_days=60)
    assert relaxed["warnings"] == []


def test_quality_cli_works_on_an_encrypted_store(tmp_path) -> None:
    import base64
    import json

    from typer.testing import CliRunner

    from janus.cli import app
    from janus.memory.store import open_store

    master = base64.b64encode(b"q" * 32).decode()
    env = {"JANUS_MASTER_KEY": master}
    db = tmp_path / "encrypted.db"
    runner = CliRunner()

    init = runner.invoke(app, ["keys", "init", "--db", str(db), "--json"], env=env)
    assert init.exit_code == 0, init.output
    store = open_store(str(db), environ=env)
    store.insert_observation(_observation("px-1"))
    store.close()

    ok = runner.invoke(
        app,
        [
            "quality",
            "ACME",
            "--as-of",
            "2026-01-02T00:00:00+00:00",
            "--db",
            str(db),
            "--json",
        ],
        env=env,
    )
    assert ok.exit_code == 0, ok.output
    assert json.loads(ok.output)["checked"] == 1

    missing = runner.invoke(
        app,
        ["quality", "ACME", "--as-of", "2026-01-02T00:00:00+00:00", "--db", str(db)],
        env={},
    )
    assert missing.exit_code == 1
    combined = missing.output + getattr(missing, "stderr", "")
    assert "key_missing" in combined
    assert "Traceback" not in combined


def test_quality_cli_rejects_naive_as_of(tmp_path) -> None:
    from typer.testing import CliRunner

    from janus.cli import app

    result = CliRunner().invoke(
        app, ["quality", "ACME", "--as-of", "2026-01-02T00:00:00"]
    )
    assert result.exit_code == 2
    combined = result.output + getattr(result, "stderr", "")
    assert "timezone offset" in combined
