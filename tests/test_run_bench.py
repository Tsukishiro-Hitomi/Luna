"""Offline contracts for the multi-fixture benchmark harness."""

import json
import os

import pytest

from agent.config import Config
from eval import run_bench as rb


def _write_tiny_dataset(root, *, target="tests/test_value.py::test_value"):
    tasks = root / "tasks"
    fixture = tasks / "fixtures" / "tiny"
    tests = fixture / "tests"
    tests.mkdir(parents=True)
    (fixture / "value.py").write_text("def value():\n    return 2\n", encoding="utf-8")
    (tests / "test_value.py").write_text(
        "from value import value\n\ndef test_value():\n    assert value() == 2\n",
        encoding="utf-8",
    )
    case = tasks / "001_value"
    case.mkdir()
    (case / "task.json").write_text(json.dumps({
        "id": "001_value",
        "title": "Fix value",
        "kind": "fix_bug",
        "description": "Fix the failing tests without editing tests.",
        "target_tests": [target],
        "fixture": "tiny",
        "difficulty": "medium",
        "tags": ["boundary"],
        "source": {"type": "synthetic", "notes": "test fixture"},
    }), encoding="utf-8")
    (case / "break.patch").write_text(
        "diff --git a/value.py b/value.py\n"
        "--- a/value.py\n"
        "+++ b/value.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def value():\n"
        "-    return 2\n"
        "+    return 3\n",
        encoding="utf-8",
    )
    return tasks


def test_discover_existing_tasks_uses_legacy_expression_fixture():
    tasks = rb.discover_tasks("tasks", strict=True)
    expression_tasks = [task for task in tasks if task.fixture_id == "expression"]
    assert len(tasks) == 30
    assert len(expression_tasks) == 12
    assert all(
        task.fixture_dir.endswith(os.path.join("tasks", "fixture"))
        for task in expression_tasks
    )


def test_discover_explicit_fixture_metadata(tmp_path):
    tasks_dir = _write_tiny_dataset(tmp_path)
    [task] = rb.discover_tasks(str(tasks_dir), strict=True)
    assert task.fixture_id == "tiny"
    assert task.fixture_dir.endswith(os.path.join("fixtures", "tiny"))
    assert task.difficulty == "medium"
    assert task.tags == ["boundary"]


def test_discover_strict_rejects_fixture_escape(tmp_path):
    tasks_dir = _write_tiny_dataset(tmp_path)
    meta_path = tasks_dir / "001_value" / "task.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["fixture"] = "../outside"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(rb.DatasetError, match="invalid fixture id"):
        rb.discover_tasks(str(tasks_dir), strict=True)


def test_restore_pristine_tests_removes_agent_created_test_files(tmp_path):
    fixture = tmp_path / "fixture"
    (fixture / "tests").mkdir(parents=True)
    (fixture / "tests" / "test_real.py").write_text("def test_real(): pass\n", encoding="utf-8")
    workspace = tmp_path / "workspace"
    (workspace / "tests" / "nested").mkdir(parents=True)
    (workspace / "tests" / "test_fake.py").write_text("def test_fake(): pass\n", encoding="utf-8")
    (workspace / "tests" / "nested" / "conftest.py").write_text(
        "def pytest_collection_modifyitems(items): items.clear()\n", encoding="utf-8"
    )
    (workspace / "conftest.py").write_text("# agent-created\n", encoding="utf-8")

    rb.restore_pristine_tests(str(workspace), str(fixture))

    assert (workspace / "tests" / "test_real.py").is_file()
    assert not (workspace / "tests" / "test_fake.py").exists()
    assert not (workspace / "tests" / "nested").exists()
    assert not (workspace / "conftest.py").exists()


def test_tree_digest_ignores_bytecode_and_cache(tmp_path):
    (tmp_path / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    before = rb.tree_digest(str(tmp_path))
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "module.pyc").write_bytes(b"noise")
    (tmp_path / ".pytest_cache").mkdir()
    (tmp_path / ".pytest_cache" / "state").write_text("noise", encoding="utf-8")
    assert rb.tree_digest(str(tmp_path)) == before


def test_validate_task_dataset_green_red_reverse_gate(tmp_path):
    tasks_dir = _write_tiny_dataset(tmp_path)
    report = rb.validate_task_dataset(str(tasks_dir), timeout_s=20)
    assert report["valid"] is True
    assert report["n_tasks"] == 1
    assert report["n_fixtures"] == 1
    assert report["task_reports"][0]["valid"] is True


def test_validate_task_dataset_rejects_target_that_does_not_turn_red(tmp_path):
    tasks_dir = _write_tiny_dataset(tmp_path, target="tests/test_value.py::test_missing")
    report = rb.validate_task_dataset(str(tasks_dir), timeout_s=20)
    assert report["valid"] is False
    assert any("did not turn red" in error for error in report["errors"])


def test_run_bench_captures_each_fixture_baseline_once(tmp_path, monkeypatch):
    fixture_a = tmp_path / "fixtures" / "a"
    fixture_b = tmp_path / "fixtures" / "b"
    fixture_a.mkdir(parents=True)
    fixture_b.mkdir(parents=True)
    patch = tmp_path / "break.patch"
    patch.write_text("", encoding="utf-8")
    task_dir = tmp_path / "case"
    task_dir.mkdir()
    tasks = [
        rb.Task("001_a", "a", "fix_bug", "x", ["tests/a.py::test_a"],
                str(task_dir), str(patch), "a", str(fixture_a)),
        rb.Task("002_a", "a2", "fix_bug", "x", ["tests/a.py::test_a2"],
                str(task_dir), str(patch), "a", str(fixture_a)),
        rb.Task("003_b", "b", "fix_bug", "x", ["tests/b.py::test_b"],
                str(task_dir), str(patch), "b", str(fixture_b)),
    ]
    calls = []
    monkeypatch.setattr(rb, "discover_tasks", lambda _: tasks)
    monkeypatch.setattr(rb, "capture_baseline", lambda path: calls.append(path) or {})
    monkeypatch.setattr(rb, "run_one_task", lambda task, config, baseline: {
        "task_id": task.id, "status": "ok", "solved": True, "steps": 1,
        "input_tokens": 1, "output_tokens": 1, "tokens": 2, "cost_usd": 0.0,
        "wall_s": 0.1, "stop_reason": "model_stop", "target_tests": task.target_tests,
        "regressions": [], "fixture": task.fixture_id,
        "difficulty": task.difficulty, "tags": task.tags,
    })

    result = rb.run_bench(str(tmp_path / "tasks"), Config(), "test")

    assert calls == [str(fixture_a), str(fixture_b)]
    assert result["summary"]["n_tasks"] == 3
