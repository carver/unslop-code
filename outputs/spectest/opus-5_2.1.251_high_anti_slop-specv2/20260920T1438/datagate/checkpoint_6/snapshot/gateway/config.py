"""Service settings: built-in defaults, a config file and the environment.

A setting is read from the ``DATAGATE_CONFIG`` file when one is named, and
from a variable of the same name in the environment, which wins over the file.
Anything unreadable raises :class:`ConfigurationError`, which stops the service
before it serves a request under a policy nobody asked for.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

#: Environment variable naming the file settings are read from.
CONFIG_FILE = "DATAGATE_CONFIG"
#: Where datasets live when ``STORAGE_DIR`` says nothing.
DEFAULT_STORAGE_DIR = Path(".datagate")

TRUE_WORDS = ("1", "true", "yes", "on")
FALSE_WORDS = ("0", "false", "no", "off")
COMMENT = "#"


class ConfigurationError(Exception):
    """A setting is unreadable, so the service must not start."""


@dataclass(frozen=True)
class Settings:
    """Everything the service reads once, at startup."""

    max_source_size: int | None = None
    origin_allowlist: tuple[str, ...] = ()
    require_tls: bool = False
    storage_dir: Path = DEFAULT_STORAGE_DIR
    cache_enabled: bool = True


def read_bytes(name: str, raw: str) -> int:
    """Read a size in bytes: a plain non-negative integer."""
    candidate = raw.strip()
    if not candidate.isdigit():
        raise ConfigurationError(
            f"{name} must be a number of bytes, not {raw!r}"
        )
    return int(candidate)


def read_boolean(name: str, raw: str) -> bool:
    """Read one of the true or false words, in any case and spacing."""
    word = raw.strip().lower()
    if word in TRUE_WORDS:
        return True
    if word in FALSE_WORDS:
        return False
    raise ConfigurationError(
        f"{name} must be one of {', '.join(TRUE_WORDS + FALSE_WORDS)}, not {raw!r}"
    )


def read_suffixes(name: str, raw: str) -> tuple[str, ...]:
    """Read a comma-separated list of domain suffixes, lowercased.

    A leading dot is how suffixes are often written, and means the same as
    without one, so it is dropped here. An empty entry names no domain and is
    a typo rather than a way of allowing everything.
    """
    suffixes = tuple(
        entry.strip().lower().lstrip(".") for entry in raw.split(",")
    )
    if not all(suffixes):
        raise ConfigurationError(f"{name} holds an empty domain suffix: {raw!r}")
    return suffixes


def read_directory(name: str, raw: str) -> Path:
    """Read a filesystem path, which has to name something."""
    candidate = raw.strip()
    if not candidate:
        raise ConfigurationError(f"{name} must name a directory, not {raw!r}")
    return Path(candidate)


#: Recognised setting names, each with the field it fills and how it is read.
SETTINGS = {
    "MAX_SOURCE_SIZE": ("max_source_size", read_bytes),
    "ORIGIN_ALLOWLIST": ("origin_allowlist", read_suffixes),
    "REQUIRE_TLS": ("require_tls", read_boolean),
    "STORAGE_DIR": ("storage_dir", read_directory),
    "CACHE_ENABLED": ("cache_enabled", read_boolean),
}


def read_config_file(path: str) -> dict[str, str]:
    """Read ``KEY=VALUE`` lines, ignoring blank ones and ``#`` comments.

    The file belongs to the service, so a line that names no known setting is
    a mistake worth reporting rather than a stray note to step over.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigurationError(f"{CONFIG_FILE} {path!r} is unreadable: {exc}") from exc

    values: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith(COMMENT):
            continue
        key, separator, value = stripped.partition("=")
        if not separator:
            raise ConfigurationError(
                f"{path} line {number} is not KEY=VALUE: {stripped!r}"
            )
        if key.strip() not in SETTINGS:
            raise ConfigurationError(
                f"{path} line {number} names an unknown setting: {key.strip()!r}"
            )
        values[key.strip()] = value
    return values


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Build the settings from the defaults, the config file and the environment."""
    source = os.environ if environ is None else environ

    raw: dict[str, str] = {}
    config_path = source.get(CONFIG_FILE)
    if config_path is not None:
        raw.update(read_config_file(config_path))
    raw.update({name: source[name] for name in SETTINGS if name in source})

    settings: dict[str, object] = {}
    for name, value in raw.items():
        attribute, read = SETTINGS[name]
        settings[attribute] = read(name, value)
    return Settings(**settings)
