"""Small value validators shared by the config and ICL loaders."""

from __future__ import annotations

from rejlib.errors import ConfigError


def mapping(value, label: str) -> dict:
    if not isinstance(value, dict):
        raise ConfigError(f"{label} must be a mapping")
    return value


def submapping(container: dict, key: str, label: str) -> dict:
    value = container.get(key, {})
    return {} if value is None else mapping(value, label)


def required_text(container: dict, key: str, label: str) -> str:
    value = container.get(key)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{label} is required and must be a non-empty string")
    return value


def positive_int(label: str, value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError(f"{label} must be a positive integer, got {value!r}")
    return value


def choice(label: str, value, allowed: tuple[str, ...]):
    if value not in allowed:
        raise ConfigError(f"{label} must be one of {', '.join(allowed)}, got {value!r}")
    return value
