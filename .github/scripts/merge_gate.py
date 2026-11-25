"""Require reviewer approval and a green tests-ok check before merge."""

from __future__ import annotations

import os
import sys

from review_gate import _api, evaluate


def main() -> None:
    ok, detail = evaluate()
    if not ok:
        print(detail)
        sys.exit(1)

    pr_number = os.environ["PR"]
    pull = _api(f"/pulls/{pr_number}")
    head = pull["head"]["sha"]
    checks = _api(f"/commits/{head}/check-runs?per_page=100")
    runs = [run for run in checks.get("check_runs", []) if run.get("name") == "tests-ok"]
    latest = max(
        runs,
        key=lambda run: str(run.get("completed_at") or run.get("started_at") or ""),
        default=None,
    )
    tests_ok = (
        latest is not None
        and latest.get("status") == "completed"
        and latest.get("conclusion") == "success"
    )
    if not tests_ok:
        print(f"tests-ok is not green on {head[:7]}")
        sys.exit(1)

    print(f"merge gate: PASS on {head[:7]}")


if __name__ == "__main__":
    main()
