import json
import os

from errors import ConfigError, IncludeCycleError
from interpolate import interpolate
from merge import deep_merge


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot load {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"configuration root must be an object: {path}")
    return data


def _load(path, env, stack):
    path = os.path.realpath(path)
    if path in stack:
        chain = " -> ".join(stack + [path])
        raise IncludeCycleError(f"include cycle: {chain}")

    data = _read_json(path)
    includes = data.pop("include", [])
    if isinstance(includes, str):
        includes = [includes]
    if not isinstance(includes, list) or not all(isinstance(item, str) for item in includes):
        raise ConfigError("include must be a string or list of strings")

    merged = {}
    next_stack = stack + [path]
    for include in includes:
        include_path = os.path.join(os.path.dirname(path), include)
        merged = deep_merge(merged, _load(include_path, env, next_stack))
    merged = deep_merge(merged, data)
    return interpolate(merged, env)


def load_config(path, env=None):
    """Load a JSON config with relative includes, merging and interpolation."""
    return _load(path, dict(env or {}), [])
