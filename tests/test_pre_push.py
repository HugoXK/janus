from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(input_text: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(ROOT / "scripts" / "pre-push")],
        input=input_text,
        text=True,
        capture_output=True,
    )


def test_pre_push_blocks_main() -> None:
    result = _run("refs/heads/topic a refs/heads/main b\n")
    assert result.returncode == 1
    assert "Direct pushes to main" in result.stderr


def test_pre_push_allows_a_feature_branch() -> None:
    result = _run("refs/heads/topic a refs/heads/topic b\n")
    assert result.returncode == 0
