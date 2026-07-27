from errors import DuplicateTaskError, PlannerError
from models import TaskSpec


def parse_tasks(items):
    """Parse JSON-like task dictionaries into validated TaskSpec objects."""
    if not isinstance(items, list):
        raise PlannerError("task input must be a list")
    parsed = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise PlannerError("each task must be an object")
        task_id = item.get("id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise PlannerError("task id must be a non-empty string")
        if task_id in seen:
            raise DuplicateTaskError(f"duplicate task id: {task_id}")
        dependencies = item.get("dependencies", [])
        if not isinstance(dependencies, list) or not all(isinstance(dep, str) for dep in dependencies):
            raise PlannerError(f"dependencies for {task_id} must be a list of strings")
        duration = item.get("duration", 1.0)
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration < 0:
            raise PlannerError(f"duration for {task_id} must be a non-negative number")
        parsed.append(TaskSpec(task_id, tuple(dependencies), float(duration)))
        seen.add(task_id)
    return parsed
