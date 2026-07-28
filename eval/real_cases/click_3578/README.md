# Reproduced case: Click pull request #3578

This case pins Click immediately before its public fix for duplicated brackets in optional
`Choice` and `DateTime` argument metavars. It is not part of controlled benchmark pass@1,
and Luna has not been run on it yet.

```bash
python eval/real_cases/click_3578/prepare_case.py /tmp/click-3578
python3.12 -m venv /tmp/click-3578-venv
/tmp/click-3578-venv/bin/pip install -r eval/real_cases/click_3578/requirements.txt
cd /tmp/click-3578
PYTHONPATH=src /tmp/click-3578-venv/bin/python -m pytest -q
```

Observed baseline: `1655 passed, 2 failed, 25 skipped, 1 xfailed`. Checking out the
published upstream source fix produces `1657 passed, 0 failed` under the same environment.
See [`case.json`](case.json) for pinned provenance and the exact focused test command.

