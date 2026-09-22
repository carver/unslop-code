"""Service settings, read once at startup.

Three layers are merged in order -- built-in defaults, the optional
`DATAGATE_CONFIG` file, then the environment -- so an operator can ship a file
of settings and still override any one of them per process. Anything the layers
cannot be made sense of raises `ConfigurationError`, which the entry point turns
into a refusal to start (T51).
"""

import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

CONFIG_PATH_VARIABLE = "DATAGATE_CONFIG"
SETTING_KEYS = ("MAX_SOURCE_SIZE", "ORIGIN_ALLOWLIST", "REQUIRE_TLS", "STORAGE_DIR", "CACHE_ENABLED")
DEFAULT_STORAGE_DIR = Path(tempfile.gettempdir()) / "datagate"

TRUE_VALUES = ("1", "true", "yes", "on")
FALSE_VALUES = ("0", "false", "no", "off")
COMMENT_MARKER = "#"


class ConfigurationError(Exception):
    """A startup setting the server refuses to run with."""


@dataclass(frozen=True)
class Settings:
    """The configured behaviour of one running service."""

    max_source_size: int | None = None
    origin_allowlist: tuple[str, ...] = ()
    require_tls: bool = False
    storage_dir: Path = DEFAULT_STORAGE_DIR
    cache_enabled: bool = True


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Merge the configuration layers and validate every value they supply.

    An environment variable wins over the same key in the config file, and a key
    neither layer names keeps its built-in default. A value that is present but
    empty leaves an optional setting unset rather than failing (T60).
    """
    source = os.environ if environ is None else environ
    values = read_config_file(source.get(CONFIG_PATH_VARIABLE))
    values.update({key: source[key] for key in SETTING_KEYS if key in source})
    return Settings(
        max_source_size=_byte_count(values.get("MAX_SOURCE_SIZE")),
        origin_allowlist=_comma_list(values.get("ORIGIN_ALLOWLIST")),
        require_tls=_boolean("REQUIRE_TLS", values.get("REQUIRE_TLS"), default=False),
        storage_dir=Path(values.get("STORAGE_DIR", "").strip() or DEFAULT_STORAGE_DIR),
        cache_enabled=_boolean("CACHE_ENABLED", values.get("CACHE_ENABLED"), default=True),
    )


def read_config_file(path: str | None) -> dict[str, str]:
    """Parse the `KEY=VALUE` lines of `DATAGATE_CONFIG`, if one was named.

    Blank lines and lines opening with `#` are ignored; every other line has to
    carry a `=`, and keys outside the settings table are kept but unused (T59).
    """
    if not path:
        return {}
    try:
        text = Path(path).read_text()
    except OSError as exc:
        raise ConfigurationError(f"Cannot read {CONFIG_PATH_VARIABLE} file {path!r}: {exc}") from None

    values = {}
    for line in text.splitlines():
        entry = line.strip()
        if not entry or entry.startswith(COMMENT_MARKER):
            continue
        key, separator, value = entry.partition("=")
        if not separator:
            raise ConfigurationError(f"{path}: expected KEY=VALUE, got {entry!r}")
        values[key.strip()] = value.strip()
    return values


def _boolean(name: str, raw: str | None, default: bool) -> bool:
    """Read one of the eight accepted literals, trimmed and case-folded (T50)."""
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    accepted = ", ".join(TRUE_VALUES + FALSE_VALUES)
    raise ConfigurationError(f"{name} must be one of {accepted} (case-insensitive), got {raw!r}")


def _byte_count(raw: str | None) -> int | None:
    """Read `MAX_SOURCE_SIZE` as whole bytes; unset or empty means no maximum (T61)."""
    value = (raw or "").strip()
    if not value:
        return None
    if not value.isdecimal():
        raise ConfigurationError(f"MAX_SOURCE_SIZE must be a whole number of bytes, got {raw!r}")
    return int(value)


def _comma_list(raw: str | None) -> tuple[str, ...]:
    """Split a list setting on commas, trimming entries and dropping empty ones."""
    return tuple(entry.strip() for entry in (raw or "").split(",") if entry.strip())
