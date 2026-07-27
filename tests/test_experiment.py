"""Offline tests for repeated, auditable benchmark campaigns."""

import json
import os

import pytest

from agent.config import Config
from eval import experiment as ex
from eval.run_bench import Task


def _result(task, cost=0.1, solved=True):
    return {
        "task_id": task.id,
        "status": "ok",
        "solved": solved,
        "steps": 3,
        "input_tokens": 100,
        "output_tokens": 20,
        "tokens": 120,
        "cost_usd": cost,
        "wall_s": 1.5,
        "stop_reason": "model_stop",
        "target_tests": task.target_tests,
        "regressions": [],
        "fixture": task.fixture_id,
        "difficulty": task.difficulty,
        "tags": task.tags,
    }


def _task(tmp_path):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    case = tmp_path / "case"
    case.mkdir()
    patch = case / "break.patch"
    patch.write_text("", encoding="utf-8")
    return Task(
        "001_demo", "demo", "fix_bug", "fix it", ["tests/test_x.py::test_x"],
        str(case), str(patch), "demo", str(fixture), "medium", ["cross-file"],
    )


def _patch_campaign_dependencies(monkeypatch, task, *, dirty=False):
    monkeypatch.setattr(ex, "repository_state", lambda root: {
        "commit": "abc1234", "dirty": dirty,
        "changes": ["README.md"] if dirty else [],
    })
    monkeypatch.setattr(ex, "task_dataset_digest", lambda path: "digest")
    monkeypatch.setattr(ex, "discover_tasks", lambda path, strict=False: [task])
    monkeypatch.setattr(ex, "capture_baseline", lambda path: {"tests/test_x.py::test_x": "passed"})


def test_wilson_interval_contains_observed_rate():
    low, high = ex.wilson_interval(8, 10)
    assert 0 < low < 0.8 < high < 1
    assert ex.wilson_interval(0, 0) == [0.0, 0.0]


def test_summarize_group_reports_sample_variance_and_errors():
    records = [
        {"solved": True, "status": "ok", "steps": 2, "tokens": 10, "cost_usd": 0.1, "wall_s": 1},
        {"solved": False, "status": "agent_error", "steps": 4, "tokens": 30, "cost_usd": 0.3, "wall_s": 3},
    ]
    summary = ex.summarize_group(records)
    assert summary["solve_rate"] == 0.5
    assert summary["invalid_or_error"] == 1
    assert summary["steps"]["mean"] == 3
    assert summary["steps"]["median"] == 3
    assert summary["steps"]["stdev"] == pytest.approx(2 ** 0.5)


def test_config_for_variant_does_not_mutate_base():
    base = Config()
    haiku = ex.config_for_variant(base, "haiku")
    retrieval = ex.config_for_variant(base, "retrieval")
    assert haiku.model == base.model_haiku
    assert retrieval.enable_retrieval is True
    assert base.model != base.model_haiku
    assert base.enable_retrieval is False
    assert haiku.price_per_mtok is not base.price_per_mtok


def test_dataset_digest_changes_with_task_content_but_ignores_readme(tmp_path):
    (tmp_path / "task.json").write_text("one", encoding="utf-8")
    first = ex.task_dataset_digest(str(tmp_path))
    (tmp_path / "README.md").write_text("documentation", encoding="utf-8")
    assert ex.task_dataset_digest(str(tmp_path)) == first
    (tmp_path / "task.json").write_text("two", encoding="utf-8")
    assert ex.task_dataset_digest(str(tmp_path)) != first


def test_aggregate_includes_paired_variant_deltas():
    manifest = {
        "campaign": "c", "repo_commit": "abc", "task_digest_sha256": "d",
        "attempts_per_task": 1,
    }
    base = {
        "variant": "baseline", "task_id": "t", "attempt_index": 1,
        "fixture": "f", "difficulty": "medium", "solved": True, "status": "ok",
        "steps": 4, "tokens": 100, "cost_usd": 0.2, "wall_s": 2,
    }
    variant = dict(base, variant="haiku", steps=6, tokens=120, cost_usd=0.1, wall_s=3)
    summary = ex.aggregate_attempts([base, variant], manifest)
    paired = summary["paired_against_baseline"]["haiku"]
    assert paired["pairs"] == 1
    assert paired["steps_mean_delta"] == 2
    assert paired["cost_usd_mean_delta"] == pytest.approx(-0.1)


def test_run_experiment_persists_and_resumes_without_duplicate_attempts(tmp_path, monkeypatch):
    task = _task(tmp_path)
    _patch_campaign_dependencies(monkeypatch, task)
    output = tmp_path / "output"
    calls = []

    def fake_run(current_task, config, baseline):
        calls.append(config.model)
        return _result(current_task)

    first = ex.run_experiment(
        str(tmp_path / "tasks"), Config(), "campaign", 2,
        ["baseline", "haiku"], 10, output_root=str(output),
        run_task=fake_run, validate=False,
    )
    assert first["n_attempt_records"] == 4
    assert len(calls) == 4
    assert (output / "manifest.json").is_file()
    assert (output / "attempts.jsonl").is_file()
    assert (output / "summary.json").is_file()
    assert (output / "report.md").is_file()

    second = ex.run_experiment(
        str(tmp_path / "tasks"), Config(), "campaign", 2,
        ["baseline", "haiku"], 10, output_root=str(output),
        run_task=fake_run, validate=False,
    )
    assert second["n_attempt_records"] == 4
    assert len(calls) == 4
    assert len(ex.load_attempts(str(output / "attempts.jsonl"))) == 4


def test_run_experiment_stops_at_cost_cap(tmp_path, monkeypatch):
    task = _task(tmp_path)
    _patch_campaign_dependencies(monkeypatch, task)
    output = tmp_path / "output"

    summary = ex.run_experiment(
        str(tmp_path / "tasks"), Config(), "budget", 3, ["baseline"], 0.5,
        output_root=str(output), run_task=lambda task, config, baseline: _result(task, cost=0.5),
        validate=False,
    )
    assert summary["n_attempt_records"] == 1
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "budget_exhausted"


def test_publish_mode_refuses_dirty_tree(tmp_path, monkeypatch):
    task = _task(tmp_path)
    _patch_campaign_dependencies(monkeypatch, task, dirty=True)
    with pytest.raises(RuntimeError, match="clean Git worktree"):
        ex.run_experiment(
            str(tmp_path / "tasks"), Config(), "official", 1, ["baseline"], 1,
            publish=True, output_root=str(tmp_path / "output"), validate=False,
        )


def test_attempt_artifact_excludes_unapproved_result_fields(tmp_path):
    task = _task(tmp_path)
    result = _result(task)
    result["full_prompt"] = "secret prompt"
    result["home_path"] = "/Users/name/private"
    record = ex._attempt_record(task, "baseline", 1, result)
    serialized = json.dumps(record)
    assert "full_prompt" not in serialized
    assert "home_path" not in serialized
    assert record["attempt_id"] == "baseline/001_demo/1"


def test_campaign_name_cannot_escape_artifact_directory(tmp_path, monkeypatch):
    task = _task(tmp_path)
    _patch_campaign_dependencies(monkeypatch, task)
    with pytest.raises(ValueError, match="campaign"):
        ex.run_experiment(
            str(tmp_path / "tasks"), Config(), "../escape", 1, ["baseline"], 1,
            output_root=str(tmp_path / "output"), validate=False,
        )


def test_manifest_command_redacts_home_directory(monkeypatch, tmp_path):
    task = _task(tmp_path)
    _patch_campaign_dependencies(monkeypatch, task)
    monkeypatch.setattr(ex.os.path, "expanduser", lambda value: "/Users/private")
    manifest = ex.build_manifest(
        str(tmp_path), str(tmp_path / "tasks"), "campaign", ["baseline"], 1, 1,
        Config(), ["python", "/Users/private/project/cli.py"],
    )
    assert manifest["command"] == ["python", "~/project/cli.py"]


def test_load_attempts_reports_corrupt_jsonl_line(tmp_path):
    path = tmp_path / "attempts.jsonl"
    path.write_text('{"ok": true}\nnot-json\n', encoding="utf-8")
    with pytest.raises(ValueError, match="line 2"):
        ex.load_attempts(str(path))
