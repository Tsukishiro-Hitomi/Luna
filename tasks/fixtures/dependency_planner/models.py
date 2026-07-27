from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class TaskSpec:
    id: str
    dependencies: Tuple[str, ...] = ()
    duration: float = 1.0
