from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "review_gate", ROOT / ".github" / "scripts" / "review_gate.py"
)
assert SPEC is not None and SPEC.loader is not None
review_gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(review_gate)

HEAD = "abcdef1234567890abcdef1234567890abcdef12"
OLD = "1111111111111111111111111111111111111111"


def _install(monkeypatch, *, author: str = "HugoXK", reviews=None, comments=None) -> None:
    monkeypatch.setenv("GH_REPO", "HugoXK/janus")
    monkeypatch.setenv("PR", "15")
    monkeypatch.setenv("REVIEWER_LOGIN", "HugoXK-bot")

    def fake_api(path: str) -> dict:
        if path == "/pulls/15":
            return {"user": {"login": author}, "head": {"sha": HEAD}}
        if path.startswith("/pulls/15/reviews"):
            return reviews or []
        if path.startswith("/issues/15/comments"):
            return comments or []
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(review_gate, "_api", fake_api)


def test_approval_must_be_on_the_head(monkeypatch) -> None:
    _install(
        monkeypatch,
        reviews=[
            {
                "user": {"login": "HugoXK-bot"},
                "state": "APPROVED",
                "commit_id": HEAD,
            }
        ],
    )
    assert review_gate.evaluate()[0] is True

    _install(
        monkeypatch,
        reviews=[
            {
                "user": {"login": "HugoXK-bot"},
                "state": "APPROVED",
                "commit_id": OLD,
            }
        ],
    )
    ok, detail = review_gate.evaluate()
    assert ok is False
    assert "APPROVED review" in detail


def test_pass_comment_must_name_the_head(monkeypatch) -> None:
    _install(
        monkeypatch,
        comments=[
            {"user": {"login": "HugoXK-bot"}, "body": f"PASS {HEAD[:7]}"}
        ],
    )
    assert review_gate.evaluate()[0] is True

    _install(
        monkeypatch,
        comments=[{"user": {"login": "HugoXK-bot"}, "body": "PASS"}],
    )
    assert review_gate.evaluate()[0] is False


def test_author_cannot_review_their_own_pr(monkeypatch) -> None:
    _install(monkeypatch, author="HugoXK-bot")
    ok, detail = review_gate.evaluate()
    assert ok is False
    assert "separate" in detail
