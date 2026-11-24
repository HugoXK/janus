"""Require a reviewer approval (or a PASS comment) on a pull request.

The reviewer identity is separate from the developer identity:
  developer: HugoXK <ke.xu@zju.edu.cn>
  reviewer:  HugoXK-bot (hugo2001xk@gmail.com)

The script is read-only. It uses the GitHub API and never runs pull request code.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def _api(path: str) -> dict:
    repo = os.environ["GH_REPO"]
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GH_TOKEN is required")
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "janus-review-gate",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"GitHub API {exc.code}: {exc.reason}") from exc


def evaluate() -> tuple[bool, str]:
    pr_number = os.environ["PR"]
    reviewer = os.environ.get("REVIEWER_LOGIN", "HugoXK-bot")
    pull = _api(f"/pulls/{pr_number}")
    author = pull["user"]["login"]
    head = pull["head"]["sha"]

    if author == reviewer:
        return False, f"reviewer {reviewer} is the PR author; identities must be separate"

    reviews = _api(f"/pulls/{pr_number}/reviews?per_page=100")
    latest: dict[str, dict] = {}
    for review in reviews:
        latest[review["user"]["login"]] = review
    approval = latest.get(reviewer)
    if approval and approval.get("state") == "APPROVED":
        return True, f"{reviewer} approved {head[:7]}"

    comments = _api(f"/issues/{pr_number}/comments?per_page=100")
    for comment in comments:
        if comment["user"]["login"] != reviewer:
            continue
        if "PASS" in (comment.get("body") or "").upper():
            return True, f"{reviewer} left a PASS comment on #{pr_number}"

    return (
        False,
        f"waiting for an approving review or a PASS comment from {reviewer} on {head[:7]}",
    )


def main() -> None:
    ok, detail = evaluate()
    print(detail)
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
