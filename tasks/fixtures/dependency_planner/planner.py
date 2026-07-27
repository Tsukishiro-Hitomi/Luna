import bisect

from errors import CycleError, MissingDependencyError, PlannerError


def _by_id(tasks):
    return {task.id: task for task in tasks}


def _validate_dependencies(tasks):
    known = _by_id(tasks)
    for task in tasks:
        for dependency in task.dependencies:
            if dependency not in known:
                raise MissingDependencyError(
                    f"task {task.id} depends on missing task {dependency}"
                )
    return known


def topological_order(tasks):
    """Return a deterministic dependency-first ordering of task IDs."""
    known = _validate_dependencies(tasks)
    indegree = {task.id: len(set(task.dependencies)) for task in tasks}
    children = {task_id: [] for task_id in known}
    for task in tasks:
        for dependency in set(task.dependencies):
            children[dependency].append(task.id)
    for values in children.values():
        values.sort()

    ready = sorted(task_id for task_id, degree in indegree.items() if degree == 0)
    order = []
    while ready:
        task_id = ready.pop(0)
        order.append(task_id)
        for child in children[task_id]:
            indegree[child] -= 1
            if indegree[child] == 0:
                bisect.insort(ready, child)
    if len(order) != len(tasks):
        blocked = sorted(task_id for task_id, degree in indegree.items() if degree > 0)
        raise CycleError(f"dependency cycle involving: {', '.join(blocked)}")
    return order


def transitive_dependencies(tasks, target):
    """Return all direct and indirect dependencies of target, sorted by ID."""
    known = _validate_dependencies(tasks)
    if target not in known:
        raise PlannerError(f"unknown target: {target}")
    found = set()

    def visit(task_id):
        for dependency in known[task_id].dependencies:
            if dependency not in found:
                found.add(dependency)
                visit(dependency)

    visit(target)
    return sorted(found)


def plan_for(tasks, targets):
    """Return a topological plan containing targets and all their dependencies."""
    known = _validate_dependencies(tasks)
    unknown = sorted(set(targets) - set(known))
    if unknown:
        raise PlannerError(f"unknown targets: {', '.join(unknown)}")
    needed = set(targets)
    for target in targets:
        needed.update(transitive_dependencies(tasks, target))
    return [task_id for task_id in topological_order(tasks) if task_id in needed]


def execution_layers(tasks):
    """Group tasks into deterministic parallel execution layers."""
    known = _validate_dependencies(tasks)
    remaining = set(known)
    complete = set()
    layers = []
    while remaining:
        current = sorted(
            task_id for task_id in remaining
            if set(known[task_id].dependencies) <= complete
        )
        if not current:
            raise CycleError(f"dependency cycle involving: {', '.join(sorted(remaining))}")
        layers.append(current)
        complete.update(current)
        remaining.difference_update(current)
    return layers


def critical_path(tasks, target=None):
    """Return the longest dependency-chain duration, optionally ending at target."""
    known = _validate_dependencies(tasks)
    if target is not None and target not in known:
        raise PlannerError(f"unknown target: {target}")
    finish = {}
    for task_id in topological_order(tasks):
        task = known[task_id]
        previous = max((finish[dep] for dep in task.dependencies), default=0.0)
        finish[task_id] = previous + task.duration
    if target is not None:
        return finish[target]
    return max(finish.values(), default=0.0)
