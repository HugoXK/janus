from __future__ import annotations

from pathlib import Path

from janus.demo import run_demo


def test_demo_output_matches_golden(capsys) -> None:
    run_demo()
    output = capsys.readouterr().out.strip()
    golden = (Path(__file__).parent / "golden" / "demo.txt").read_text().strip()
    assert output == golden
