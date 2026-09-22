"""Service configuration: built-in defaults, the ``DATAGATE_CONFIG`` file, environment.

Each source overrides the one before it, so a setting given directly in the environment
wins over the same setting in the config file, which in turn wins over the default. A
value the server cannot make sense of raises ``ConfigError`` rather than being guessed
at, which fails startup.
"""

import os
from dataclasses import dataclass
from pathlib import Path

CONFIG_VARIABLE = "DATAGATE_CONFIG"
SETTINGS = (
    "MAX_SOURCE_SIZE",
    "ORIGIN_ALLOWLIST",
    "REQUIRE_TLS",
    "STORAGE_DIR",
    "CACHE_ENABLED",
)
DEFAULT_STORAGE_DIR = Path("datagate-data")
TRUE_VALUES = ("1", "true", "yes", "on")
FALSE_VALUES = ("0", "false", "no", "off")


class ConfigError(Exception):
    """A setting the server cannot start with."""


@dataclass(frozen=True)
class Config:
    """The settings in force for one server process.

    ``max_source_size`` of ``None`` means sources are unbounded, and an empty
    ``origin_allowlist`` means requests are accepted whatever their ``Referer``.
    """

    max_source_size: int | None
    origin_allowlist: tuple[str, ...]
    require_tls: bool
    storage_dir: Path
    cache_enabled: bool


def load_config() -> Config:
    """Return the configuration: the config file, with the environment read over it."""
    values = read_config_file(os.environ.get(CONFIG_VARIABLE))
    values.update({name: os.environ[name] for name in SETTINGS if name in os.environ})

    storage_dir = values.get("STORAGE_DIR")
    return Config(
        max_source_size=read_size(values.get("MAX_SOURCE_SIZE")),
        origin_allowlist=read_suffixes(values.get("ORIGIN_ALLOWLIST")),
        require_tls=read_boolean(
            "REQUIRE_TLS", values.get("REQUIRE_TLS"), default=False
        ),
        storage_dir=Path(storage_dir) if storage_dir else DEFAULT_STORAGE_DIR,
        cache_enabled=read_boolean(
            "CACHE_ENABLED", values.get("CACHE_ENABLED"), default=True
        ),
    )


def read_config_file(path: str | None) -> dict[str, str]:
    """Return the settings written in the file ``DATAGATE_CONFIG`` names, if any.

    The file holds one ``KEY=VALUE`` setting per line; blank lines and lines opening
    with ``#`` are ignored. A file that cannot be read, or a line that names no known
    setting, raises ``ConfigError``.
    """
    if path is None:
        return {}

    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read {CONFIG_VARIABLE} file {path!r}: {exc}") from exc

    values: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        key, separator, value = entry.partition("=")
        if not separator or key.strip() not in SETTINGS:
            raise ConfigError(f"{path} line {number}: not a setting: {entry!r}")
        values[key.strip()] = value.strip()
    return values


def read_boolean(name: str, raw: str | None, *, default: bool) -> bool:
    """Return ``raw`` as a boolean, accepting only the documented spellings.

    Surrounding space and case are ignored; anything else, including an empty value,
    raises ``ConfigError``.
    """
    if raw is None:
        return default

    value = raw.strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False

    accepted = ", ".join(TRUE_VALUES + FALSE_VALUES)
    raise ConfigError(f"{name} must be one of {accepted}; got {raw!r}")


def read_size(raw: str | None) -> int | None:
    """Return ``MAX_SOURCE_SIZE`` as a byte count, or ``None`` when it is unset."""
    if raw is None:
        return None

    value = raw.strip()
    if not value.isdigit():
        raise ConfigError(
            f"MAX_SOURCE_SIZE must be a whole number of bytes; got {raw!r}"
        )
    return int(value)


def read_suffixes(raw: str | None) -> tuple[str, ...]:
    """Return ``ORIGIN_ALLOWLIST`` as the lowercased domain suffixes it lists.

    The entries are comma separated, and a setting listing none of them -- as an unset
    or empty value does -- leaves the allowlist off.
    """
    if raw is None:
        return ()
    return tuple(entry.strip().lower() for entry in raw.split(",") if entry.strip())
