import re

from errors import ConfigError


_VARIABLE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _expand_string(value, env):
    def replace(match):
        name, default = match.group(1), match.group(2)
        if name in env:
            return str(env[name])
        if default is not None:
            return default
        raise ConfigError(f"missing environment variable: {name}")

    return _VARIABLE.sub(replace, value)


def interpolate(value, env):
    """Recursively expand ${NAME} and ${NAME:-default} placeholders."""
    if isinstance(value, str):
        return _expand_string(value, env)
    if isinstance(value, list):
        return [interpolate(item, env) for item in value]
    if isinstance(value, dict):
        return {key: interpolate(item, env) for key, item in value.items()}
    return value
