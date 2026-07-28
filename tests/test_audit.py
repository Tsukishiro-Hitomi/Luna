"""Offline tests for committed evidence and the real-case registry."""

import json
import shutil
from pathlib import Path

from eval.audit import audit_repository, verify_experiment_artifact, verify_real_case_index


def test_committed_evidence_recomputes_exactly():
    report = audit_repository(".")
    assert report["valid"], report["errors"]
    assert report["artifact_campaigns"] >= 1
    assert report["real_cases"] >= 1


def test_tampered_experiment_summary_is_rejected(tmp_path):
    source = Path("eval/artifacts/multi_repo_v1")
    target = tmp_path / "campaign"
    shutil.copytree(source, target)
    summary_path = target / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["n_attempt_records"] -= 1
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    errors = verify_experiment_artifact(str(target))
    assert any("summary.json" in error for error in errors)


def test_real_case_registry_matches_case_metadata():
    errors = verify_real_case_index("eval/real_cases")
    assert errors == []


def test_real_case_registry_rejects_unpinned_commit(tmp_path):
    cases = tmp_path / "real_cases"
    case_dir = cases / "demo"
    case_dir.mkdir(parents=True)
    for name in ("reproduction.patch", "prepare.py"):
        (case_dir / name).write_text("", encoding="utf-8")
    result = {
        "case_id": "demo",
        "upstream": {
            "url": "https://example.com/repo", "issue_url": "https://example.com/issue/1",
            "license": "MIT", "base_commit": "short",
        },
    }
    (case_dir / "case.json").write_text(json.dumps(result), encoding="utf-8")
    index = {
        "schema_version": 1,
        "cases": [{
            "case_id": "demo", "directory": "demo", "status": "reproduced",
            "upstream_url": "https://example.com/repo",
            "issue_url": "https://example.com/issue/1", "license": "MIT",
            "base_commit": "short", "upstream_fix_commit": "b" * 40,
            "reproduction_patch": "reproduction.patch",
            "preparation_script": "prepare.py", "test_command": "pytest",
            "result_file": "case.json", "included_in_controlled_pass_at_1": False,
        }],
    }
    (cases / "index.json").write_text(json.dumps(index), encoding="utf-8")
    errors = verify_real_case_index(str(cases))
    assert any("40-character SHA" in error for error in errors)


def test_real_case_registry_rejects_path_escape(tmp_path):
    cases = tmp_path / "real_cases"
    cases.mkdir()
    index = {
        "schema_version": 1,
        "cases": [{
            "case_id": "escape", "directory": "../private", "status": "planned",
            "upstream_url": "https://example.com/repo",
            "issue_url": "https://example.com/issues/1", "license": "MIT",
            "base_commit": "a" * 40, "upstream_fix_commit": "b" * 40,
            "reproduction_patch": "reproduction.patch",
            "preparation_script": "prepare.py", "test_command": "pytest",
            "result_file": "case.json", "included_in_controlled_pass_at_1": False,
        }],
    }
    (cases / "index.json").write_text(json.dumps(index), encoding="utf-8")
    errors = verify_real_case_index(str(cases))
    assert any("stay within" in error for error in errors)
