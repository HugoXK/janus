## Summary

<!-- What changed, and why? One or two paragraphs. -->

## Linked issues

<!-- Closes #... -->

## Type of change

- [ ] Feature
- [ ] Fix
- [ ] Refactor
- [ ] Tests
- [ ] Docs / CI

## Verification

- [ ] `uv run ruff check .`
- [ ] `uv run pytest`
- [ ] `uv run janus schema check`
- [ ] `uv run janus demo`
- [ ] No secrets, API keys, or licensed data added
- [ ] New public behavior is documented

## Review

Reviewer checklist:

- [ ] Scope matches the linked issue
- [ ] Tests cover the new behavior and the failure path
- [ ] Point-in-time rules are preserved (no future data, no overwriting as-filed facts)
- [ ] No financial advice or return promises in copy
- [ ] Merge only after `tests-ok`, `review-gate`, and `merge-gate` are green
