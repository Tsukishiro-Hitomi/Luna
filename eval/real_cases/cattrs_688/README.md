# Reproduced case: cattrs pull request #688

This case pins cattrs immediately before its fix for nested generic classes with stringified
annotations. The converter attempts to resolve annotations on a parameterized alias instead
of the generic origin and raises `TypeError`. It is not part of controlled benchmark pass@1.

```bash
python eval/real_cases/cattrs_688/prepare_case.py /tmp/cattrs-688
python3.12 -m venv /tmp/cattrs-688-venv
/tmp/cattrs-688-venv/bin/pip install -r eval/real_cases/cattrs_688/requirements.txt
cd /tmp/cattrs-688
PYTHONPATH=src /tmp/cattrs-688-venv/bin/python -m pytest -q -o addopts='' \
  --ignore=tests/preconf --ignore=tests/test_preconf.py
```

Observed core-suite baseline: `883 passed, 2 failed, 15 xfailed`; optional serializer adapter
tests are excluded because their third-party dependencies are outside this case. The published
upstream source fix produces `885 passed, 0 failed` under the same scope. See
[`case.json`](case.json) for pinned provenance and the exact focused test command.

## Observed Luna run

Luna solved the case in 13 steps using 77,050 input and 1,590 output tokens, for an estimated
`$0.4250`. Its [`luna.patch`](luna.patch) matches the upstream repair behavior and passed the
core suite with `885 passed, 0 failed` and no regressions.
