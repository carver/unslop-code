"""Behaviour switches taken from `--setting` flags and project configuration.

Every setting is a boolean the command line may override. The values a
command runs with are the defaults, overlaid with what the project
configuration says, overlaid with what `--setting` asks for.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from typing import Dict, Iterable

from .source import SourceError

BOOLEANS = {"true": True, "false": False}


class SettingError(SourceError):
    """A `--setting` flag naming no setting, or a value none of them take."""


@dataclass(frozen=True)
class Settings:
    """What the commands may be asked to do differently."""

    case_insensitive: bool = True
    """Whether a typed prefix matches names of any case."""
    dynamic_params: bool = True
    """Whether unannotated parameters take the types their call sites pass."""
    smart_sys_path: bool = True
    """Whether import roots are detected as well as configured."""
    add_bracket: bool = False
    """Whether a function or class completion inserts its opening bracket."""

    def with_overrides(self, overrides: Dict[str, bool]) -> "Settings":
        """These settings, with the named ones replaced."""
        return replace(self, **overrides)


def parse_settings(flags: Iterable[str]) -> Dict[str, bool]:
    """The overrides a sequence of `key=value` flags asks for."""
    named = {field.name for field in fields(Settings)}
    overrides = {}
    for flag in flags:
        key, separator, value = flag.partition("=")
        if not separator or key not in named:
            raise SettingError(f"unknown setting: {flag}")
        if value.lower() not in BOOLEANS:
            raise SettingError(f"invalid value for {key}: {value}")
        overrides[key] = BOOLEANS[value.lower()]
    return overrides
