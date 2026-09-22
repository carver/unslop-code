"""Service settings: their defaults, their sources, and the types they are read at."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from datagate_core.config_file import read_config_file
from datagate_core.errors import ConfigurationError

#: Environment variable naming the optional config file.
CONFIG_PATH_VARIABLE = "DATAGATE_CONFIG"

#: The settings datagate owns; any other key in the config file is ignored (T61).
SETTING_NAMES = (
    "MAX_SOURCE_SIZE",
    "ORIGIN_ALLOWLIST",
    "REQUIRE_TLS",
    "STORAGE_DIR",
    "CACHE_ENABLED",
)

#: The only spellings a boolean setting accepts, trimmed and compared lower-cased.
TRUE_VALUES = ("1", "true", "yes", "on")
FALSE_VALUES = ("0", "false", "no", "off")

#: Where datasets live when `STORAGE_DIR` says nothing (T70).
DEFAULT_STORAGE_DIR = Path("datagate-data")


@dataclass(frozen=True)
class Settings:
    """The five service settings, already coerced to the types their users want."""

    max_source_size: int | None
    origin_allowlist: tuple[str, ...]
    require_tls: bool
    storage_dir: Path
    cache_enabled: bool


def load_settings(environ: dict[str, str] | None = None) -> Settings:
    """Merge the three configuration sources into the settings datagate runs on.

    Later sources win, so a direct environment variable overrides the
    `DATAGATE_CONFIG` file, which overrides the built-in defaults (T57).
    Anything unreadable - a value of the wrong type, a malformed config line, a
    config file that will not open - raises `ConfigurationError`, which is what
    makes invalid configuration a startup failure rather than a request failure.
    """
    environ = os.environ if environ is None else environ
    values = read_config_file(environ.get(CONFIG_PATH_VARIABLE)) | {
        name: environ[name] for name in SETTING_NAMES if name in environ
    }
    return Settings(
        max_source_size=_optional(values, "MAX_SOURCE_SIZE", _byte_count),
        origin_allowlist=_suffix_list(values.get("ORIGIN_ALLOWLIST", "")),
        require_tls=_boolean(values, "REQUIRE_TLS", default=False),
        storage_dir=_storage_dir(values.get("STORAGE_DIR", "")),
        cache_enabled=_boolean(values, "CACHE_ENABLED", default=True),
    )


def _optional(values: dict[str, str], name: str, coerce: Callable[[str, str], int]) -> int | None:
    """Coerce a setting whose default is "unset"; an empty value means unset (T60)."""
    raw = values.get(name, "").strip()
    return coerce(name, raw) if raw else None


def _byte_count(name: str, raw: str) -> int:
    """Read a size in bytes: a plain non-negative decimal integer, nothing else (T62)."""
    if not raw.isdecimal():
        raise ConfigurationError(
            f"{name} must be a non-negative whole number of bytes, got {raw!r}"
        )
    return int(raw)


def _suffix_list(raw: str) -> tuple[str, ...]:
    """Split a comma-separated list value, dropping entries that are only space."""
    return tuple(entry.strip() for entry in raw.split(",") if entry.strip())


def _storage_dir(raw: str) -> Path:
    """The configured storage path, or the built-in default when it is unset."""
    configured = raw.strip()
    return Path(configured) if configured else DEFAULT_STORAGE_DIR


def _boolean(values: dict[str, str], name: str, default: bool) -> bool:
    """Read a strict boolean: one of the two lists, case-insensitive and trimmed."""
    if name not in values:
        return default
    setting = values[name].strip().lower()
    if setting in TRUE_VALUES:
        return True
    if setting in FALSE_VALUES:
        return False
    raise ConfigurationError(
        f"{name} must be one of {', '.join(TRUE_VALUES + FALSE_VALUES)}, got {values[name]!r}"
    )
