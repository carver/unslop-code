"""Service configuration: built-in defaults, a config file, then the environment.

Every setting is resolved once, when the app is built, by layering the three
sources in the order the spec gives them — a later layer overrides an earlier
one — and validating what they supply. Anything unusable is a `ConfigError`, so
a misconfigured process fails at startup instead of serving.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path

CONFIG_FILE = "DATAGATE_CONFIG"
COMMENT = "#"
DEFAULT_STORAGE_DIR = ".datagate"

# The only spellings a boolean setting accepts, matched trimmed and lowercased.
BOOLEANS = {
    "1": True,
    "true": True,
    "yes": True,
    "on": True,
    "0": False,
    "false": False,
    "no": False,
    "off": False,
}

DIGITS = re.compile(r"[0-9]+")


class ConfigError(Exception):
    """An unusable configuration: the server must not start."""


@dataclass(frozen=True)
class Settings:
    """The validated configuration one app instance runs under."""

    max_source_size: int | None
    origin_allowlist: tuple[str, ...]
    require_tls: bool
    storage_dir: str
    cache_enabled: bool


def _boolean(name: str, raw: str) -> bool:
    """One of the eight accepted spellings, case and surrounding space aside."""
    decision = BOOLEANS.get(raw.strip().lower())
    if decision is None:
        raise ConfigError(f"{name} must be one of {', '.join(BOOLEANS)}, got '{raw}'")
    return decision


def _byte_count(name: str, raw: str) -> int:
    """A whole number of bytes; `0` is a limit of zero, not the absence of one."""
    literal = raw.strip()
    if not DIGITS.fullmatch(literal):
        raise ConfigError(f"{name} must be a whole number of bytes, got '{raw}'")
    return int(literal)


def _suffix_list(name: str, raw: str) -> tuple[str, ...]:
    """Comma-separated domain suffixes, normalised for matching.

    A leading dot is how the same intent is often written, so `.example.com`
    is stored as `example.com`; an entry with nothing in it names no domain and
    is dropped, which leaves `ORIGIN_ALLOWLIST=` meaning no allowlist at all.
    """
    entries = (entry.strip().lower().lstrip(".") for entry in raw.split(","))
    return tuple(entry for entry in entries if entry)


def _directory(name: str, raw: str) -> str:
    """A path to a directory; an empty one names nothing."""
    path = raw.strip()
    if not path:
        raise ConfigError(f"{name} must be a path, got an empty value")
    return path


# Each setting's parser and its built-in default, keyed by the name all three
# configuration sources spell it with.
SETTINGS = {
    "MAX_SOURCE_SIZE": (_byte_count, None),
    "ORIGIN_ALLOWLIST": (_suffix_list, ()),
    "REQUIRE_TLS": (_boolean, False),
    "STORAGE_DIR": (_directory, DEFAULT_STORAGE_DIR),
    "CACHE_ENABLED": (_boolean, True),
}


def load_settings(environ=os.environ) -> Settings:
    """Resolve the settings `environ` — and the config file it names — describe."""
    supplied = {**_file_values(environ.get(CONFIG_FILE)), **environ}
    return Settings(
        **{
            name.lower(): parse(name, supplied[name]) if name in supplied else default
            for name, (parse, default) in SETTINGS.items()
        }
    )


def _file_values(path: str | None) -> dict[str, str]:
    """The `KEY=VALUE` pairs of the config file, or nothing when none is named.

    Keys no setting claims are left alone: the file's grammar is satisfied and
    the service is not the only thing that may be configured from it.
    """
    if path is None:
        return {}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"{CONFIG_FILE} '{path}' could not be read: {exc}") from exc
    return dict(_settings_lines(text, path))


def _settings_lines(text: str, path: str):
    """Yield each configuring line of `text` as a trimmed key and value."""
    for number, line in enumerate(text.splitlines(), start=1):
        entry = line.strip()
        if not entry or entry.startswith(COMMENT):
            continue
        key, separator, value = entry.partition("=")
        if not separator or not key.strip():
            raise ConfigError(f"{path} line {number} is not KEY=VALUE: '{entry}'")
        yield key.strip(), value.strip()
