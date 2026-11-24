from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN = (
    "guaranteed return",
    "guaranteed profit",
    "risk-free profit",
    "buy now",
    "sell now",
)


def test_public_copy_does_not_promise_returns() -> None:
    text = "\n".join(
        [
            (ROOT / "README.md").read_text().lower(),
            (ROOT / "README.zh.md").read_text().lower(),
        ]
    )
    for phrase in FORBIDDEN:
        assert phrase not in text, f"forbidden claim in public copy: {phrase}"


def test_disclaimer_is_present() -> None:
    text = "\n".join(
        [
            (ROOT / "README.md").read_text().lower(),
            (ROOT / "README.zh.md").read_text().lower(),
        ]
    )
    assert "not investment advice" in text or "不是投资建议" in text
