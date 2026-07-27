# Real-repository case: itsdangerous issue #237

This is one independently judged case study. It is not part of the controlled benchmark
and is not counted toward pass@1.

## Provenance

- upstream: [pallets/itsdangerous](https://github.com/pallets/itsdangerous)
- license: BSD-3-Clause
- public issue: [#237](https://github.com/pallets/itsdangerous/issues/237)
- pinned pre-fix commit: `15a2e0d9b4bdaa38144c947a9aa04ffd49826700`
- upstream fix: `41ec419632aae3533ff12838044eeddd9cd1311f`

Issue #237 reported a compatibility regression: `Signer` and `Serializer` should accept
`salt=None`, but the pre-fix version stores `None` and later attempts to concatenate it
with bytes while deriving a signing key.

## Reproduce

```bash
python eval/real_cases/itsdangerous_237/prepare_case.py /tmp/itsdangerous-237
python3 -m venv /tmp/itsdangerous-237-venv
/tmp/itsdangerous-237-venv/bin/pip install \
  -r eval/real_cases/itsdangerous_237/requirements.txt
/tmp/itsdangerous-237-venv/bin/pip install -e /tmp/itsdangerous-237 --no-build-isolation
/tmp/itsdangerous-237-venv/bin/python -m pytest -q /tmp/itsdangerous-237/tests
```

Expected baseline: `421 passed, 16 failed`. The reproduction patch is committed locally by
the preparation script so Luna's real-repository anti-cheat restoration protects it.

## Observed Luna run

```text
model:       anthropic/claude-opus-4.8
result:      solved
baseline:    421 passed / 16 failed
post-judge:  437 passed / 0 failed
regressions: 0
steps:       12
tokens:      73,590 input / 2,031 output
cost:        $0.4187 estimated
agent wall:  45.9 s
```

The independently rerun full upstream suite passed after applying [`luna.patch`](luna.patch).
The Luna patch is behaviorally aligned with the upstream repair: it preserves `None` through
`Serializer` and maps `None` to the default salt inside `Signer`.

## Limitations

- This is a single historical issue selected because it has a deterministic offline test.
- The reproduction adds regression tests based on the public issue and upstream fix behavior.
- A successful repair here does not establish a general solve rate on arbitrary repositories.
