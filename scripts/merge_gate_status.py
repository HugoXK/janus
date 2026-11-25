from __future__ import annotations

import json
import sys
from typing import Any

REQUIRED = ("tests-ok", "review-gate", "merge-gate")


def latest_runs(
    check_runs: list[dict[str, Any]],
    required: tuple[str, ...] = REQUIRED,
) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for run in check_runs:
        name = run.get("name")
        if name not in required:
            continue
        stamp = str(run.get("completed_at") or run.get("started_at") or "")
        current = latest.get(name)
        if current is None or stamp > str(current.get("_stamp") or ""):
            latest[name] = {**run, "_stamp": stamp}
    return latest


def evaluate(
    check_runs: list[dict[str, Any]],
    required: tuple[str, ...] = REQUIRED,
) -> tuple[list[str], list[tuple[str, dict[str, Any]]]]:
    latest = latest_runs(check_runs, required)
    missing = [name for name in required if name not in latest]
    failed = [
        (name, run)
        for name, run in latest.items()
        if run.get("conclusion") != "success"
    ]
    return missing, failed


def main() -> None:
    payload = json.load(sys.stdin)
    if isinstance(payload, list):
        check_runs = payload
    else:
        check_runs = payload.get("check_runs", [])
    head = sys.argv[1] if len(sys.argv) > 1 else ""
    missing, failed = evaluate(check_runs)
    if missing:
        print("missing required checks: " + ", ".join(missing))
        raise SystemExit(1)
    if failed:
        for name, run in failed:
            print(
                f"{name}: {run.get('status')}/{run.get('conclusion')} "
                f"{run.get('html_url') or ''}"
            )
        raise SystemExit(1)
    print(f"latest required checks are green on {head[:7]}")


if __name__ == "__main__":
    main()
