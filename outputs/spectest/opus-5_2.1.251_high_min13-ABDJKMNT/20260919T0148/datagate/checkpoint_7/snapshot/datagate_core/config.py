"""Startup settings, resolved from the defaults, `DATAGATE_CONFIG` and the environment."""

import os
import re
from dataclasses import dataclass

from .config_file import read_config_file
from .errors import ConfigurationError

CONFIG_VARIABLE = "DATAGATE_CONFIG"
SETTING_NAMES = (
    "MAX_SOURCE_SIZE",
    "ORIGIN_ALLOWLIST",
    "REQUIRE_TLS",
    "STORAGE_DIR",
    "CACHE_ENABLED",
)

DEFAULT_STORAGE_DIR = "datagate_data"
TRUE_VALUES = ("1", "true", "yes", "on")
FALSE_VALUES = ("0", "false", "no", "off")
BYTE_COUNT = re.compile(r"\d+")


@dataclass(frozen=True)
class Settings:
    """The configuration the service reads once, at startup."""

    max_source_size: int | None = None
    origin_allowlist: tuple = ()
    require_tls: bool = False
    storage_dir: str = DEFAULT_STORAGE_DIR
    cache_enabled: bool = True


def load_settings(environ=None):
    """Resolve the settings, raising `ConfigurationError` on anything unusable.

    The three sources are applied in ascending precedence (AMBIGUITIES T56): the
    built-in defaults below, then the `DATAGATE_CONFIG` file, then the environment.
    Keys neither source mentions keep their default, and keys the file carries that
    are not settings are ignored (AMBIGUITIES T58).
    """
    environ = os.environ if environ is None else environ
    values = read_config_file(environ.get(CONFIG_VARIABLE))
    values.update((name, environ[name]) for name in SETTING_NAMES if name in environ)

    return Settings(
        max_source_size=_byte_count("MAX_SOURCE_SIZE", values),
        origin_allowlist=_suffixes("ORIGIN_ALLOWLIST", values),
        require_tls=_boolean("REQUIRE_TLS", values, default=False),
        storage_dir=values.get("STORAGE_DIR", DEFAULT_STORAGE_DIR),
        cache_enabled=_boolean("CACHE_ENABLED", values, default=True),
    )


def _boolean(name, values, default):
    """Read one of the documented boolean spellings, case-folded and trimmed."""
    if name not in values:
        return default

    value = values[name].strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False

    accepted = ", ".join(TRUE_VALUES + FALSE_VALUES)
    raise ConfigurationError(f"{name} must be one of {accepted}; got {values[name]!r}.")


def _byte_count(name, values):
    """Read an optional count of bytes; a signed, fractional or suffixed one is a failure.

    An unset setting means no limit, and a size is never negative (AMBIGUITIES T61).
    """
    if name not in values:
        return None

    value = values[name].strip()
    if not BYTE_COUNT.fullmatch(value):
        raise ConfigurationError(
            f"{name} must be a non-negative whole number of bytes; got {values[name]!r}."
        )
    return int(value)


def _suffixes(name, values):
    """Read a comma-separated list of domain suffixes, dropping blanks and leading dots.

    A value that parses to nothing is the same as an unset one (AMBIGUITIES T64).
    """
    entries = (entry.strip().lstrip(".") for entry in values.get(name, "").split(","))
    return tuple(entry for entry in entries if entry)
