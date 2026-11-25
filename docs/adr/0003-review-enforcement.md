# ADR 0003: Review enforcement on a free private repository

## Status

Accepted.

## Context

Janus uses pull requests, a separate reviewer account, an identity check, and
two review gates. Branch protection and repository rulesets require GitHub Pro
or a public repository, so on the current free private repository the gates are
status checks, not physical merge blockers.

The reviewer is an outside collaborator. The free plan only allows write access
for that role, so the process also relies on the `identity` check to keep the
reviewer from authoring code.

## Decision

1. Keep the PR + reviewer + `identity` + `review-gate` + `merge-gate` process.
2. Add a local `pre-push` guard that refuses a direct push to `main`.
3. Treat the GitHub checks as the process gate while the repository is private.
4. When the repository becomes public or the account has GitHub Pro, enable
   branch protection with these required checks:
   - `tests-ok`
   - `review-gate`
   - `merge-gate`

## Consequences

- A local contributor who installs the hook cannot push to `main` by accident.
- A determined contributor can bypass the hook with `git push --no-verify`; the
  server-side gate remains documentation and CI until branch protection is
  available.
- No identity or permission table needs to live in the README.
