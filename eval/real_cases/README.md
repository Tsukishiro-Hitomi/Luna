# Real-repository evaluation cases

These cases provide external-validity evidence separately from Luna's controlled synthetic
benchmark. A case is never included in controlled pass@1, and `reproduced` does not mean Luna
solved it.

| case | project | public report/fix | status | verified baseline |
|---|---|---|---|---:|
| `itsdangerous_237` | Pallets itsdangerous | issue #237 | solved | 421 passed / 16 failed |
| `click_3578` | Pallets Click | pull request #3578 | reproduced | 1655 passed / 2 failed |
| `packaging_1345` | PyPA Packaging | pull request #1345 | reproduced | 62353 passed / 3 failed |
| `cattrs_688` | python-attrs cattrs | pull request #688 | reproduced | 883 passed / 2 failed |

## Status lifecycle

- `planned`: provenance selected, reproduction not independently verified.
- `reproduced`: the pinned pre-fix commit fails the tracked regression tests and the public
  upstream repair passes the same test scope; Luna has not been run.
- `solved`: Luna was run, its generated patch was independently judged, and run metrics were
  recorded. Unsuccessful Luna runs must remain recorded rather than being silently removed.

Each directory contains a machine-readable `case.json`, a test-only `reproduction.patch`, a
networked preparation script, pinned test dependencies, and human reproduction instructions.
The registry at [`index.json`](index.json) is checked by `luna audit` for unique IDs, pinned
commits, provenance consistency, safe paths, explicit pass@1 separation, and status/result
consistency.

