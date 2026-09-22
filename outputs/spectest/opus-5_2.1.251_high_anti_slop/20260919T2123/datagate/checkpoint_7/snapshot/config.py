"""Service settings: built-in defaults, the `DATAGATE_CONFIG` file, then environment variables."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

CONFIG_FILE_VAR = "DATAGATE_CONFIG"
COMMENT_PREFIX = "#"
LIST_SEPARATOR = ","
TRUE_VALUES = ("1", "true", "yes", "on")
FALSE_VALUES = ("0", "false", "no", "off")
DEFAULT_STORAGE_DIR = Path("datagate-data")


@dataclass(frozen=True)
class Settings:
    """Everything the service is configured with, already validated."""

    max_source_size: int | None = None
    origin_allowlist: tuple[str, ...] = ()
    require_tls: bool = False
    storage_dir: Path = DEFAULT_STORAGE_DIR
    cache_enabled: bool = True


def parse_bool(raw: str) -> bool:
    """Read one of the documented boolean spellings, case and surrounding space aside.

    Anything else is a configuration mistake rather than a default to fall back on, so it raises
    and the service refuses to start.
    """
    value = raw.strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    accepted = ", ".join(TRUE_VALUES + FALSE_VALUES)
    raise ValueError(f"must be one of {accepted}, got {raw!r}")


def _parse_byte_count(raw: str) -> int:
    """Read a size in bytes; `isdecimal` is what rules out signs, decimals and text."""
    if not raw.isdecimal():
        raise ValueError(f"must be a whole number of bytes, got {raw!r}")
    return int(raw)


def _parse_suffixes(raw: str) -> tuple[str, ...]:
    """Read a comma-separated list of domain suffixes, normalised for comparison.

    Hostnames are matched case-insensitively and a suffix may be written with or without its
    leading dot, so both are stripped here rather than at every comparison.
    """
    entries = (entry.strip().strip(".").lower() for entry in raw.split(LIST_SEPARATOR))
    return tuple(entry for entry in entries if entry)


# Each setting's attribute on `Settings` and the parser that validates its raw text.
SETTINGS = {
    "MAX_SOURCE_SIZE": ("max_source_size", _parse_byte_count),
    "ORIGIN_ALLOWLIST": ("origin_allowlist", _parse_suffixes),
    "REQUIRE_TLS": ("require_tls", parse_bool),
    "STORAGE_DIR": ("storage_dir", Path),
    "CACHE_ENABLED": ("cache_enabled", parse_bool),
}


def load_settings(environ: Mapping[str, str] = os.environ) -> Settings:
    """Build the settings from the defaults, the config file and the environment, in that order.

    Raises `ValueError` for an unusable config file or setting value and `OSError` when the file
    named by `DATAGATE_CONFIG` cannot be read; either way the service reports it and exits.
    """
    raw = read_config_file(environ.get(CONFIG_FILE_VAR))
    raw.update({name: environ[name] for name in SETTINGS if name in environ})

    values = {}
    for name, text in raw.items():
        attribute, parse = SETTINGS[name]
        try:
            values[attribute] = parse(text.strip())
        except ValueError as exc:
            raise ValueError(f"{name} {exc}") from exc
    return Settings(**values)


def read_config_file(path: str | None) -> dict[str, str]:
    """Read the `KEY=VALUE` lines of the config file, ignoring blank and commented ones.

    An unset `DATAGATE_CONFIG` simply means there is no file to read; a line that names no
    setting, or names one datagate does not have, is a mistake worth reporting by name.
    """
    if path is None:
        return {}
    values = {}
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text or text.startswith(COMMENT_PREFIX):
            continue
        name, separator, value = text.partition("=")
        setting = name.strip()
        if not separator:
            raise ValueError(f"{path} line {number}: expected KEY=VALUE, got {text!r}")
        if setting not in SETTINGS:
            raise ValueError(f"{path} line {number}: unknown setting {setting!r}")
        values[setting] = value
    return values
