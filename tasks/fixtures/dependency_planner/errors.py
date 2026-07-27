class PlannerError(Exception):
    """Base error for task parsing and dependency planning."""


class DuplicateTaskError(PlannerError):
    """Raised when two task specifications share an ID."""


class MissingDependencyError(PlannerError):
    """Raised when a dependency references an unknown task."""


class CycleError(PlannerError):
    """Raised when the task dependency graph contains a cycle."""
