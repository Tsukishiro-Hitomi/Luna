from copy import deepcopy

from errors import ConfigError


def deep_merge(base, override):
    """Return a recursive dict merge without mutating either input.

    Nested dictionaries merge recursively. Every other value, including lists, is
    replaced by the override value.
    """
    if not isinstance(base, dict) or not isinstance(override, dict):
        raise ConfigError("deep_merge expects two dictionaries")
    result = deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result
