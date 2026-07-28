# Reproduced case: Packaging pull request #1345

This case pins Packaging immediately before its parser fix for trailing newlines. Python's
regular-expression `$` anchor accepts a position before a final newline, which allowed invalid
marker and requirement strings through. It is not part of controlled benchmark pass@1.

```bash
python eval/real_cases/packaging_1345/prepare_case.py /tmp/packaging-1345
python3.12 -m venv /tmp/packaging-1345-venv
/tmp/packaging-1345-venv/bin/pip install -r eval/real_cases/packaging_1345/requirements.txt
cd /tmp/packaging-1345
PYTHONPATH=src /tmp/packaging-1345-venv/bin/python -m pytest -q
```

Observed baseline: `62353 passed, 3 failed, 1 skipped`. Checking out the published upstream
source fix produces `62356 passed, 0 failed`. See [`case.json`](case.json) for pinned
provenance and the exact focused test command.

## Observed Luna run

Luna independently identified the regular-expression end-anchor issue and solved it in 7
steps using 61,714 input and 851 output tokens, for an estimated `$0.329845`. The generated
[`luna.patch`](luna.patch) passed the full suite with `62356 passed, 0 failed`.
