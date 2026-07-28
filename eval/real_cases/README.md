# Real-repository evaluation cases

This directory contains historical bugs from public Python projects. Each repository is pinned
immediately before its upstream fix, then patched with the regression tests needed to reproduce
the bug. These runs are kept separate from the synthetic benchmark.

| case | project | public report/fix | status | verified baseline |
|---|---|---|---|---:|
| `itsdangerous_237` | Pallets itsdangerous | issue #237 | solved | 421 passed / 16 failed |
| `click_3578` | Pallets Click | pull request #3578 | solved | 1655 passed / 2 failed |
| `packaging_1345` | PyPA Packaging | pull request #1345 | solved | 62353 passed / 3 failed |
| `cattrs_688` | python-attrs cattrs | pull request #688 | solved | 883 passed / 2 failed |

## Status values

- `planned`: the case has been selected but not reproduced yet.
- `reproduced`: the pinned commit fails the added regression tests, while the upstream fix
  passes them. Luna has not been run.
- `solved`: Luna has been run, the resulting patch has been tested, and the run metrics have
  been recorded. Failed runs are kept as part of the result.

Each case includes `case.json`, a test-only `reproduction.patch`, a preparation script, pinned
test dependencies, reproduction notes, and—after a successful run—`luna.patch`. Click,
Packaging, and cattrs were selected and reproduced before Luna was run; the three runs cost
`$0.9660` in total.

`luna audit` checks [`index.json`](index.json), referenced files, pinned commits, metadata, and
the consistency between each case's status and recorded result. Four cases are far too few to
estimate a general repair rate, so the table above should be read as individual case studies.
