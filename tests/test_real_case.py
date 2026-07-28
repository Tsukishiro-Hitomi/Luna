"""Static, offline integrity checks for the published real-repository case."""

import importlib.util
import json
from pathlib import Path


CASE_DIR = Path("eval/real_cases/itsdangerous_237")
INDEX = Path("eval/real_cases/index.json")


def _case():
    return json.loads((CASE_DIR / "case.json").read_text(encoding="utf-8"))


def test_real_case_is_explicitly_separate_from_pass_at_one():
    case = _case()
    assert case["schema_version"] == 1
    assert "not included in benchmark pass@1" in case["classification"]


def test_real_case_pins_public_provenance_and_license():
    upstream = _case()["upstream"]
    assert upstream["url"] == "https://github.com/pallets/itsdangerous"
    assert upstream["issue_url"].endswith("/issues/237")
    assert upstream["license"] == "BSD-3-Clause"
    assert len(upstream["base_commit"]) == 40
    assert len(upstream["upstream_fix_commit"]) == 40


def test_real_case_verdict_counts_are_consistent():
    case = _case()
    baseline = case["reproduction"]["baseline"]
    verdict = case["luna_run"]["post_verdict"]
    assert baseline == {"passed": 421, "failed": 16, "error": 0, "skipped": 0}
    assert verdict == {"passed": 437, "failed": 0, "error": 0, "skipped": 0}
    assert case["luna_run"]["fixed"] == baseline["failed"]
    assert case["luna_run"]["regressions"] == 0


def test_real_case_referenced_artifacts_exist_and_are_relative():
    case = _case()
    names = [case["reproduction"]["patch"], case["luna_run"]["patch"]]
    assert names == ["reproduction.patch", "luna.patch"]
    assert all((CASE_DIR / name).is_file() for name in names)


def test_real_case_patches_contain_no_machine_paths_or_credentials():
    content = "\n".join(
        (CASE_DIR / name).read_text(encoding="utf-8")
        for name in ("reproduction.patch", "luna.patch")
    )
    assert "/Users/" not in content
    assert "ANTHROPIC_API_KEY" not in content
    assert "sk-" not in content


def test_prepare_script_constants_match_case_metadata():
    spec = importlib.util.spec_from_file_location("prepare_case", CASE_DIR / "prepare_case.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    upstream = _case()["upstream"]
    assert module.UPSTREAM.rstrip(".git") == upstream["url"].rstrip(".git")
    assert module.BASE_COMMIT == upstream["base_commit"]


def test_real_case_dependencies_are_version_pinned():
    requirements = (CASE_DIR / "requirements.txt").read_text(encoding="utf-8").splitlines()
    assert requirements
    assert all("==" in line for line in requirements if line.strip())


def test_real_case_is_registered_in_index():
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    entry = next(item for item in index["cases"] if item["case_id"] == "itsdangerous_237")
    assert entry["status"] == "solved"
    assert entry["included_in_controlled_pass_at_1"] is False
    assert entry["base_commit"] == _case()["upstream"]["base_commit"]
