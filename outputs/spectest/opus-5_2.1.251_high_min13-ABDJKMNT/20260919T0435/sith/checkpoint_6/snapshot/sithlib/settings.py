"""The behaviours a request may override with `--setting key=value`."""

from __future__ import annotations

from dataclasses import dataclass, fields

from .source import SithError

_BOOLEANS = {"true": True, "false": False}


@dataclass(frozen=True)
class Settings:
    """What a command does when nothing asks it to do otherwise."""

    case_insensitive: bool = True
    dynamic_params: bool = True
    smart_sys_path: bool = True
    add_bracket: bool = False


#: The settings a project file or a `--setting` flag may name.
NAMES = tuple(field.name for field in fields(Settings))


def parse(flags: list[str]) -> dict[str, bool]:
    """The overrides written as `key=value`, refusing anything else."""
    return dict(_override(text) for text in flags)


def _override(text: str) -> tuple[str, bool]:
    name, separator, value = text.partition("=")
    if not separator or name not in NAMES:
        raise SithError(f"unknown setting: {text}")
    if value.lower() not in _BOOLEANS:
        raise SithError(f"setting {name} takes true or false, not {value!r}")
    return name, _BOOLEANS[value.lower()]


def resolve(configured: dict[str, bool], overrides: dict[str, bool]) -> Settings:
    """Defaults, overlaid with the project configuration, overlaid with the flags."""
    return Settings(**{**configured, **overrides})
