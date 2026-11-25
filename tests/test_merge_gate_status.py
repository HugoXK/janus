from __future__ import annotations

from scripts.merge_gate_status import evaluate


def _run(name: str, conclusion: str, stamp: str) -> dict:
    return {
        "name": name,
        "status": "completed",
        "conclusion": conclusion,
        "completed_at": stamp,
    }


def test_latest_success_wins_over_an_older_failure() -> None:
    missing, failed = evaluate(
        [
            _run("review-gate", "failure", "2026-01-01T00:00:00Z"),
            _run("review-gate", "success", "2026-01-01T00:10:00Z"),
            _run("merge-gate", "success", "2026-01-01T00:10:00Z"),
            _run("tests-ok", "success", "2026-01-01T00:10:00Z"),
        ]
    )
    assert missing == []
    assert failed == []


def test_latest_failure_is_not_hidden_by_an_older_success() -> None:
    missing, failed = evaluate(
        [
            _run("review-gate", "success", "2026-01-01T00:00:00Z"),
            _run("review-gate", "failure", "2026-01-01T00:10:00Z"),
            _run("merge-gate", "success", "2026-01-01T00:10:00Z"),
            _run("tests-ok", "success", "2026-01-01T00:10:00Z"),
        ]
    )
    assert missing == []
    assert [name for name, _ in failed] == ["review-gate"]


def test_missing_required_check_fails() -> None:
    missing, failed = evaluate(
        [
            _run("tests-ok", "success", "2026-01-01T00:10:00Z"),
            _run("merge-gate", "success", "2026-01-01T00:10:00Z"),
        ]
    )
    assert missing == ["review-gate"]
    assert failed == []


def test_unrelated_checks_are_ignored() -> None:
    missing, failed = evaluate(
        [
            _run("lint", "failure", "2026-01-01T00:10:00Z"),
            _run("tests-ok", "success", "2026-01-01T00:10:00Z"),
            _run("review-gate", "success", "2026-01-01T00:10:00Z"),
            _run("merge-gate", "success", "2026-01-01T00:10:00Z"),
        ]
    )
    assert missing == []
    assert failed == []
