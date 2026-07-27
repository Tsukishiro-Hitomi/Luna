import pytest

from errors import CycleError, MissingDependencyError, PlannerError
from models import TaskSpec
from planner import (
    critical_path,
    execution_layers,
    plan_for,
    topological_order,
    transitive_dependencies,
)


def task(task_id, dependencies=(), duration=1):
    return TaskSpec(task_id, tuple(dependencies), float(duration))


def test_topological_order_is_dependency_first():
    tasks = [task("deploy", ["test"]), task("test", ["build"]), task("build")]
    assert topological_order(tasks) == ["build", "test", "deploy"]


def test_topological_order_is_deterministic_for_independent_tasks():
    tasks = [task("z"), task("a"), task("m")]
    assert topological_order(tasks) == ["a", "m", "z"]


def test_missing_dependency_raises():
    with pytest.raises(MissingDependencyError, match="missing task compile"):
        topological_order([task("test", ["compile"])])


def test_cycle_raises_with_blocked_tasks():
    tasks = [task("a", ["b"]), task("b", ["a"])]
    with pytest.raises(CycleError, match="a, b"):
        topological_order(tasks)


def test_transitive_dependencies_include_full_chain():
    tasks = [task("deploy", ["test"]), task("test", ["build"]), task("build")]
    assert transitive_dependencies(tasks, "deploy") == ["build", "test"]


def test_transitive_dependencies_deduplicate_diamond():
    tasks = [
        task("root"), task("left", ["root"]), task("right", ["root"]),
        task("final", ["left", "right"]),
    ]
    assert transitive_dependencies(tasks, "final") == ["left", "right", "root"]


def test_unknown_transitive_target_raises():
    with pytest.raises(PlannerError, match="unknown target"):
        transitive_dependencies([task("a")], "missing")


def test_plan_for_includes_dependencies_but_excludes_unrelated_tasks():
    tasks = [task("build"), task("test", ["build"]), task("deploy", ["test"]), task("docs")]
    assert plan_for(tasks, ["deploy"]) == ["build", "test", "deploy"]


def test_plan_for_multiple_targets_shares_dependencies():
    tasks = [task("build"), task("unit", ["build"]), task("lint", ["build"]), task("docs")]
    assert plan_for(tasks, ["unit", "lint"]) == ["build", "lint", "unit"]


def test_execution_layers_group_parallel_work():
    tasks = [task("build"), task("unit", ["build"]), task("lint", ["build"]), task("ship", ["unit", "lint"])]
    assert execution_layers(tasks) == [["build"], ["lint", "unit"], ["ship"]]


def test_execution_layers_put_independent_tasks_together():
    assert execution_layers([task("b"), task("a")]) == [["a", "b"]]


def test_execution_layers_detect_cycle():
    with pytest.raises(CycleError):
        execution_layers([task("a", ["b"]), task("b", ["a"])])


def test_critical_path_uses_longest_parent_branch():
    tasks = [
        task("start", duration=2), task("fast", ["start"], 1),
        task("slow", ["start"], 5), task("finish", ["fast", "slow"], 3),
    ]
    assert critical_path(tasks, "finish") == 10


def test_critical_path_without_target_returns_graph_maximum():
    tasks = [task("a", duration=2), task("b", ["a"], 4), task("independent", duration=9)]
    assert critical_path(tasks) == 9


def test_critical_path_empty_graph_is_zero():
    assert critical_path([]) == 0
