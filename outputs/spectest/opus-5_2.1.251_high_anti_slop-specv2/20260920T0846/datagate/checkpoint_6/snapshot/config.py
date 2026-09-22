"""Service configuration: built-in defaults, a config file and the environment.

Every setting is read once at startup, from the least to the most specific
source: the defaults below, then the ``KEY=VALUE`` file ``DATAGATE_CONFIG``
names, then the environment variables themselves. A setting the server cannot
make sense of is a ``ConfigError``, which stops it from starting rather than
leaving it running under a configuration nobody asked for.
"""

import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

CONFIG_FILE = "DATAGATE_CONFIG"
COMMENT = "#"
LIST_SEPARATOR = ","

MAX_SOURCE_SIZE = "MAX_SOURCE_SIZE"
ORIGIN_ALLOWLIST = "ORIGIN_ALLOWLIST"
REQUIRE_TLS = "REQUIRE_TLS"
STORAGE_DIR = "STORAGE_DIR"
CACHE_ENABLED = "CACHE_ENABLED"
SETTINGS = (MAX_SOURCE_SIZE, ORIGIN_ALLOWLIST, REQUIRE_TLS, STORAGE_DIR, CACHE_ENABLED)

DEFAULT_STORAGE_DIR = Path(tempfile.gettempdir()) / "datagate-datasets"

TRUE_WORDS = ("1", "true", "yes", "on")
FALSE_WORDS = ("0", "false", "no", "off")

WHOLE_NUMBER = re.compile(r"\d+")


class ConfigError(ValueError):
    """A setting the server cannot start with."""


@dataclass(frozen=True)
class Config:
    """The settings one server run works under.

    ``max_source_size`` is ``None`` and ``origin_allowlist`` empty when their
    settings are unset, which is how "no maximum" and "every origin passes"
    are spelled.
    """

    max_source_size: int | None
    origin_allowlist: tuple[str, ...]
    require_tls: bool
    storage_dir: Path
    cache_enabled: bool


def load(environ: Mapping[str, str] | None = None) -> Config:
    """Resolve the configuration, with environment variables having the last word."""
    environ = os.environ if environ is None else environ
    values = _from_file(environ.get(CONFIG_FILE)) | _from_environment(environ)
    return Config(
        max_source_size=_byte_count(values.get(MAX_SOURCE_SIZE)),
        origin_allowlist=_suffixes(values.get(ORIGIN_ALLOWLIST)),
        require_tls=_boolean(values.get(REQUIRE_TLS), REQUIRE_TLS, default=False),
        storage_dir=Path(values.get(STORAGE_DIR) or DEFAULT_STORAGE_DIR),
        cache_enabled=_boolean(values.get(CACHE_ENABLED), CACHE_ENABLED, default=True),
    )


def _from_environment(environ: Mapping[str, str]) -> dict[str, str]:
    return {name: environ[name] for name in SETTINGS if name in environ}


def _from_file(path: str | None) -> dict[str, str]:
    """Read the settings out of the file ``DATAGATE_CONFIG`` names, if any.

    Lines are ``KEY=VALUE``; blank ones and comments are skipped. A line that
    carries no ``=``, or that names something that is not a datagate setting,
    is a mistake in the file rather than a setting to apply. An unset — or
    empty — ``DATAGATE_CONFIG`` names no file, which leaves the defaults and
    the environment to settle every setting between them.
    """
    if not path:
        return {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ConfigError(f"Cannot read {CONFIG_FILE} file {path!r}: {exc}") from exc

    values = {}
    for number, line in enumerate(lines, start=1):
        statement = line.strip()
        if not statement or statement.startswith(COMMENT):
            continue
        key, separator, value = statement.partition("=")
        if not separator or key.strip() not in SETTINGS:
            raise ConfigError(f"{path} line {number} is not a datagate setting: {statement!r}")
        values[key.strip()] = value.strip()
    return values


def _boolean(raw: str | None, name: str, default: bool) -> bool:
    """Read one of the documented true or false words, in any capitalisation."""
    if raw is None:
        return default
    word = raw.strip().lower()
    if word in TRUE_WORDS:
        return True
    if word in FALSE_WORDS:
        return False
    accepted = ", ".join(TRUE_WORDS + FALSE_WORDS)
    raise ConfigError(f"{name} must be one of {accepted}; got {raw!r}")


def _byte_count(raw: str | None) -> int | None:
    """Read a size limit in bytes; an unset limit means sources may be any size."""
    if raw is None:
        return None
    limit = raw.strip()
    if not WHOLE_NUMBER.fullmatch(limit):
        raise ConfigError(f"{MAX_SOURCE_SIZE} must be a whole number of bytes; got {raw!r}")
    return int(limit)


def _suffixes(raw: str | None) -> tuple[str, ...]:
    """Read a comma separated list of domain suffixes, ignoring empty entries."""
    if raw is None:
        return ()
    return tuple(entry.strip() for entry in raw.split(LIST_SEPARATOR) if entry.strip())
