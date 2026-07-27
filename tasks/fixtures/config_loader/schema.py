from errors import ValidationError


def get_path(config, dotted_path):
    current = config
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise ValidationError(f"missing required setting: {dotted_path}")
        current = current[part]
    return current


def validate(config, required=(), types=None):
    """Validate required dotted paths and optional expected Python types."""
    for path in required:
        get_path(config, path)
    for path, expected in (types or {}).items():
        value = get_path(config, path)
        if not isinstance(value, expected):
            name = getattr(expected, "__name__", str(expected))
            raise ValidationError(f"{path} must be {name}, got {type(value).__name__}")
    return config
