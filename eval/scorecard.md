# Luna scorecard

- date: `2026-07-27T16:39:48`  ·  commit: `4834227`
- model: `anthropic/claude-opus-4.8`  ·  retrieval: `False`  ·  self-correction: `False`
- guardrails: max_steps=`30`, cost_budget=`$0.5`, run_tests_timeout=`60s`, judge_timeout=`60s`

## Per-task (baseline)

| task | solved | steps | tokens | cost($) | wall(s) | stop_reason | regressions |
|---|:--:|--:|--:|--:|--:|---|---|
| 001_mul_precedence | ✅ | 6 | 22522 | 0.1244 | 21.1 | model_stop | - |
| 002_eval_division_stub | ✅ | 9 | 32731 | 0.1765 | 26.4 | model_stop | - |
| 003_multidigit_number | ✅ | 6 | 29373 | 0.1583 | 21.8 | model_stop | - |
| 004_unary_minus | ✅ | 5 | 20879 | 0.1125 | 14.0 | model_stop | - |
| 005_eval_negation_stub | ✅ | 6 | 16448 | 0.0909 | 17.9 | model_stop | - |
| 006_eval_subtraction | ✅ | 5 | 18475 | 0.1010 | 17.0 | model_stop | - |
| 007_eval_multiplication | ✅ | 5 | 19145 | 0.1039 | 15.6 | model_stop | - |
| 008_tokenize_float | ✅ | 5 | 18274 | 0.0991 | 15.8 | model_stop | - |
| 009_bare_dot | ✅ | 6 | 20930 | 0.1155 | 20.8 | model_stop | - |
| 010_tokenize_ops | ✅ | 6 | 16420 | 0.0913 | 16.4 | model_stop | - |
| 011_parser_trailing | ✅ | 6 | 21185 | 0.1152 | 18.4 | model_stop | - |
| 012_eval_addition | ✅ | 6 | 21968 | 0.1171 | 18.2 | model_stop | - |

## Summary

- **pass@1 = 12/12 = 100%**
- avg steps: 5.9  ·  avg tokens: 21529  ·  avg cost: $0.1171  ·  total cost: $1.41  ·  avg wall: 18.6s

## Ablations

| variant | model | retrieval | self-corr | pass@1 | avg steps | avg cost($) | total($) |
|---|---|:--:|:--:|:--:|--:|--:|--:|
| baseline | claude-opus-4.8 | False | False | 100% | 5.9 | 0.1171 | 1.41 |
| haiku | claude-haiku-4.5 | False | False | 100% | 7.2 | 0.0351 | 0.42 |
| retrieval | claude-opus-4.8 | True | False | 100% | 5.5 | 0.1714 | 2.06 |

> 小任务集 + 采样随机性下，条件间的小差异可能是噪声；n_attempts=1。
