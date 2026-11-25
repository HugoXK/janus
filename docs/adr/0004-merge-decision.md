# ADR 0004: Merge decisions use the latest required check per context

## Status

Accepted.

## Context

GitHub retains every check run attached to a head commit. A gate such as
`review-gate` fails before approval and succeeds after a review; both runs remain
listed for the same head. `gh pr checks` shows both, so a green PR can look red,
and a manual `gh pr merge` does not evaluate the checks at all on a repository
without branch protection.

The old `merge_gate.py` used `any(check == success)`, which could accept an older
success even when the latest `tests-ok` run had failed.

## Decision

1. `scripts/merge-pr.sh` is the supported merge path. It selects the **latest**
   run per required context for the current head and refuses to merge unless
   `tests-ok`, `review-gate`, and `merge-gate` are all successful.
2. `merge_gate.py` also selects the latest `tests-ok` run instead of any run.
3. `review_gate.py` orders reviews by `submitted_at` before choosing the latest.
4. Branch protection with the same required checks remains the only server-side
   enforcement; it requires a public repository or GitHub Pro.

## Consequences

- `make merge-pr PR=<number>` replaces manual `gh pr merge`.
- A stale failure from an earlier event cannot hide a newer success, and a newer
  failure cannot be hidden by an older success.
- A direct `gh pr merge` can still bypass the script; the pre-push guard and the
  ADR make that an explicit process violation, not an accident.
