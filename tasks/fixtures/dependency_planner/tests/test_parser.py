import pytest

from errors import DuplicateTaskError, PlannerError
from parser import parse_tasks


def test_parses_defaults():
    [task] = parse_tasks([{"id": "build"}])
    assert task.id == "build"
    assert task.dependencies == ()
    assert task.duration == 1.0


def test_parses_dependencies_and_duration():
    [task] = parse_tasks([{"id": "test", "dependencies": ["build"], "duration": 2}])
    assert task.dependencies == ("build",)
    assert task.duration == 2.0


def test_duplicate_ids_raise():
    with pytest.raises(DuplicateTaskError, match="duplicate task id"):
        parse_tasks([{"id": "build"}, {"id": "build"}])


def test_empty_id_raises():
    with pytest.raises(PlannerError, match="non-empty"):
        parse_tasks([{"id": ""}])


def test_dependencies_must_be_strings():
    with pytest.raises(PlannerError, match="list of strings"):
        parse_tasks([{"id": "build", "dependencies": [1]}])


def test_negative_duration_raises():
    with pytest.raises(PlannerError, match="non-negative"):
        parse_tasks([{"id": "build", "duration": -1}])


def test_boolean_is_not_a_duration():
    with pytest.raises(PlannerError, match="non-negative"):
        parse_tasks([{"id": "build", "duration": True}])
