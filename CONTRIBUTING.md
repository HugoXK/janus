# Contributing

Thanks for taking a look at Janus.

## Development

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run janus demo
```

## Principles

- **Point-in-time or it didn't happen.** Every feature that reads data must
  support an `as_of` view.
- **LLMs reason; software computes.** Indicators, backtests, and calibration
  stay deterministic.
- **No advice, no execution.** Janus is research tooling. Do not add broker
  execution or return promises.
- **Free by default.** The core loop must run without a paid API.
- **Small surfaces.** Prefer a narrow, testable module over a large framework.

## Merging

Use `make merge-pr PR=<number>` (or `scripts/merge-pr.sh <number>`). It selects
the latest run per required check for the PR head and refuses to merge unless
`tests-ok`, `review-gate`, and `merge-gate` are green. Do not use `gh pr merge`
directly.

## Pull requests

- Never push directly to `main`; every change goes through a PR.
- A PR needs a review and green checks before merge.
- Required checks: `tests-ok`, `review-gate`, and `merge-gate`.
- Add or update tests.
- Keep the demo working: `uv run janus demo`.
- Update the relevant ADR or doc when a design decision changes.
- Do not commit API keys, broker credentials, or licensed data.
- Link the issue from `docs/BACKLOG.md` and keep the PR focused.
