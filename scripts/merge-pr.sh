#!/usr/bin/env bash
set -euo pipefail

PR="${1:?usage: scripts/merge-pr.sh <pr-number>}"
REPO="${REPO:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"
HEAD="$(gh pr view "$PR" -R "$REPO" --json headRefOid -q .headRefOid)"

echo "PR #$PR head $HEAD"
gh api "repos/$REPO/commits/$HEAD/check-runs?per_page=100" \
  | python3 "$(dirname "$0")/merge_gate_status.py" "$HEAD"

gh pr merge "$PR" -R "$REPO" --merge --delete-branch
