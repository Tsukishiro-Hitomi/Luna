class ConfigError(Exception):
    """Base error for configuration loading and validation."""


class IncludeCycleError(ConfigError):
    """Raised when configuration files include each other cyclically."""


class ValidationError(ConfigError):
    """Raised when a loaded configuration violates its schema."""
