"""Everything a request needs beyond the cursor it was given.

Settings come from three places, each beating the one before it: the defaults
declared here, the project configuration, and the ``--setting`` flags of the
command line.  The options also carry the project configuration itself and, in
interpreter mode, the namespaces a name may fall back to.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from pathlib import Path

from .config import ProjectConfig
from .errors import SithError
from .namespaces import Namespaces

_BOOLEANS = {"true": True, "false": False}


@dataclass(frozen=True)
class Settings:
    """The behaviour ``--setting`` may change, with the defaults it starts from."""

    case_insensitive: bool = True
    dynamic_params: bool = True
    smart_sys_path: bool = True
    add_bracket: bool = False

    @classmethod
    def resolve(cls, overrides: list[str], config: ProjectConfig) -> "Settings":
        """The defaults as the project configures them and the flags override them."""
        return replace(cls(smart_sys_path=config.smart_sys_path), **parse(overrides))


@dataclass(frozen=True)
class Options:
    """The settings, project configuration and namespaces of one request."""

    settings: Settings = Settings()
    config: ProjectConfig = ProjectConfig()
    namespaces: Namespaces | None = None

    @classmethod
    def build(cls, root: Path, overrides: list[str],
              namespaces: Namespaces | None) -> "Options":
        """The options of a request made against the project rooted at ``root``."""
        config = ProjectConfig.load(root)
        return cls(Settings.resolve(overrides, config), config, namespaces)


DEFAULTS = Options()


def parse(overrides: list[str]) -> dict[str, bool]:
    """The ``key=value`` flags as the settings they name; later ones win."""
    return dict(_override(text) for text in overrides)


def _override(text: str) -> tuple[str, bool]:
    name, _, value = text.partition("=")
    if name not in {field.name for field in fields(Settings)}:
        raise SithError(f"unknown setting: {name}")
    if value.lower() not in _BOOLEANS:
        raise SithError(f"setting {name} takes true or false, not {value!r}")
    return name, _BOOLEANS[value.lower()]
