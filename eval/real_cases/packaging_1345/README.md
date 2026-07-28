# Reproduced case: Packaging pull request #1345

This case pins Packaging immediately before its parser fix for trailing newlines. Python's
regular-expression `$` anchor accepts a position before a final newline, which allowed invalid
marker and requirement strings through. It is not part of controlled benchmark pass@1, and
Luna has not been run on it yet.

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

