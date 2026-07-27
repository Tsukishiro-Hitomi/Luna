# Luna experiment: multi_repo_v1

- commit: `acdbc5e`
- task digest: `c834ce4ed0fbfd799da203df3e0afcf0cb8014736b6c563edae1fc37277cb8c2`
- attempts per task: `3`
- recorded attempts: `270`
- total estimated cost: `$28.49`

## Variants

| variant | solved | solve rate | 95% Wilson CI | steps mean±sd | cost mean±sd | invalid |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 90/90 | 100.0% | 95.9%–100.0% | 6.37±0.88 | $0.1319±0.0313 | 0 |
| haiku | 90/90 | 100.0% | 95.9%–100.0% | 8.26±1.47 | $0.0378±0.0131 | 0 |
| retrieval | 90/90 | 100.0% | 95.9%–100.0% | 5.71±0.96 | $0.1468±0.0379 | 0 |

## Per-fixture solve rate

| variant | config_loader | dependency_planner | expression |
|---|---:|---:|---:|
| baseline | 100.0% | 100.0% | 100.0% |
| haiku | 100.0% | 100.0% | 100.0% |
| retrieval | 100.0% | 100.0% | 100.0% |

## Paired deltas against baseline

Positive values mean the variant used more resources than baseline.

| variant | pairs | solve-rate Δ | steps Δ | tokens Δ | cost Δ | wall Δ |
|---|---:|---:|---:|---:|---:|---:|
| haiku | 90 | +0.0% | +1.89 | +9701 | $-0.0942 | -1.46s |
| retrieval | 90 | +0.0% | -0.66 | +3204 | $+0.0149 | -1.57s |

> Repeated-run solve rate is an empirical proportion across attempts. It is not
> presented as a deterministic guarantee. Harness errors remain in the denominator.
