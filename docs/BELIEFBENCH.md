# BeliefBench

BeliefBench is the lookahead-free evaluation harness. A scenario is a historical
question with an `as_of` time and a later `resolved_at` time. The runner must
answer using only evidence available at `as_of`.

## Scenario schema

```json
{
  "id": "aapl-2026-02",
  "entity_id": "AAPL",
  "as_of": "2026-02-01T00:00:00+00:00",
  "resolved_at": "2026-03-01T00:00:00+00:00",
  "question": "Will AAPL be higher in one month?",
  "resolution": {"outcome": 1},
  "horizon": "1M",
  "tags": ["mega-cap", "tech"]
}
```

- `resolved_at` must be strictly after `as_of`; the constructor rejects
  otherwise.
- `resolution.outcome` must be 0 or 1 for scoring.
- `tags` are optional slices for the report.

## Runner

```python
from janus.eval.beliefbench import BeliefBench, ScenarioResult

bench = BeliefBench.load("scenarios.json")

def runner(scenario):
    # Use only data with published_at <= scenario.as_of.
    return ScenarioResult(
        scenario_id=scenario.id,
        probability=0.7,
        outcome=float(scenario.resolution["outcome"]),
        evidence=("sec:10-k:...",),
    )

report = bench.run(runner)
```

The harness validates the scenario id, probability range, outcome value, and
resolution time. It does not inspect how the runner built its evidence; that is
the agent's responsibility and the reason `as_of` is passed explicitly.

## Report

`BenchmarkReport` contains:

- `n`, `brier`, `log_loss`, `ece`;
- `directional_accuracy` (`P(up) >= 0.5` vs realized outcome);
- `citation_coverage` (share of results with non-empty evidence);
- `by_horizon` and `by_tag` slices.

## Baselines

`janus.eval.baselines.run_baselines(bench)` returns `always_up`, `always_down`,
and `random` reports. A number without a baseline is marketing; every published
result should name the baseline and the sample.

## Rules

1. No future data: the runner must respect `scenario.as_of`.
2. No restated data: use as-filed facts.
3. No cherry-picking: report the full scenario set and the baseline.
4. Keep the scenario file and the report in the same commit for reproducibility.
