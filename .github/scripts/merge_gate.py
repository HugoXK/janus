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
    runs = checks.get("check_runs", [])
    tests_ok = any(
        run.get("name") == "tests-ok"
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
        for run in runs
    )
    if not tests_ok:
        print(f"tests-ok is not green on {head[:7]}")
        sys.exit(1)

    print(f"merge gate: PASS on {head[:7]}")


if __name__ == "__main__":
    main()
