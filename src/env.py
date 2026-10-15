"""Environment parsing without loading dotenv or application configuration."""

import math
import os


class ConfigError(ValueError):
    """An environment variable contains an invalid configuration value."""


def env_str(name: str, default: str) -> str:
    """Use the default for missing, empty, or whitespace-only values."""
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def env_int(name: str, default: int) -> int:
    """Read an integer without exposing invalid values in errors."""
    value = env_str(name, "")
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        raise ConfigError(f"{name} must be an integer") from None


def env_float(name: str, default: float) -> float:
    """Read a finite number without exposing invalid values in errors."""
    value = env_str(name, "")
    if not value:
        return default
    try:
        number = float(value)
    except ValueError:
        raise ConfigError(f"{name} must be a finite number") from None
    if not math.isfinite(number):
        raise ConfigError(f"{name} must be a finite number")
    return number
