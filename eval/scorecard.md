# Luna scorecard

The current official scorecard is the reproducible `multi_repo_v1` campaign:

- commit: `acdbc5e`
- task digest: `c834ce4ed0fbfd799da203df3e0afcf0cb8014736b6c563edae1fc37277cb8c2`
- dataset: 30 tasks across 3 independent fixtures
- attempts: 3 per task and condition; 270 total
- harness errors: 0
- total estimated cost: $28.49

| variant | solved | solve rate (95% Wilson CI) | steps mean±sd | cost mean±sd |
|---|---:|---:|---:|---:|
| baseline | 90/90 | 100% (95.9%–100%) | 6.37±0.88 | $0.1319±0.0313 |
| haiku | 90/90 | 100% (95.9%–100%) | 8.26±1.47 | $0.0378±0.0131 |
| retrieval | 90/90 | 100% (95.9%–100%) | 5.71±0.96 | $0.1468±0.0379 |

The complete generated report is available at
[`eval/artifacts/multi_repo_v1/report.md`](artifacts/multi_repo_v1/report.md), with the
machine-readable [summary](artifacts/multi_repo_v1/summary.json),
[manifest](artifacts/multi_repo_v1/manifest.json), and all 270
[attempt records](artifacts/multi_repo_v1/attempts.jsonl).

> All conditions reached the ceiling of this controlled dataset. Efficiency comparisons are
> informative; solve-rate separation requires harder tasks. These results do not imply a
> universal repair rate on arbitrary repositories.
