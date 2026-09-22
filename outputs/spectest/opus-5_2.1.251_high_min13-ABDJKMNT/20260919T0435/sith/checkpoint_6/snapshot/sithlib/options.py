"""What every command carries besides its cursor: settings, project, namespaces."""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from . import settings as setting_flags
from .config import ProjectConfig
from .modules import ModuleIndex
from .namespaces import Namespaces
from .settings import Settings
from .source import SithError


@dataclass(frozen=True)
class Request:
    """One project root as a command sees it, once its flags have been applied."""

    root: str
    config: ProjectConfig
    settings: Settings
    namespaces: Namespaces

    def index(self) -> ModuleIndex:
        """The search path this request resolves imports against."""
        return ModuleIndex(self.root, self.config.search_paths(self.settings.smart_sys_path))


@dataclass(frozen=True)
class Options:
    """The flags a command was given, before it knows which root they apply to."""

    overrides: tuple[tuple[str, bool], ...] = ()
    namespaces: Namespaces = Namespaces()

    @classmethod
    def of(cls, arguments: argparse.Namespace) -> "Options":
        overrides = setting_flags.parse(getattr(arguments, "setting", None) or [])
        return cls(tuple(overrides.items()), _namespaces(arguments))

    def at(self, root: str) -> Request:
        """Read the project configuration of `root` and settle the settings on it."""
        config = ProjectConfig.load(root)
        settings = setting_flags.resolve(dict(config.settings), dict(self.overrides))
        return Request(root, config, settings, self.namespaces)


#: A request that was given no flags at all.
DEFAULT = Options()


def _namespaces(arguments: argparse.Namespace) -> Namespaces:
    """The live namespaces of an interpreter-mode request; none without the flag."""
    path = getattr(arguments, "namespaces", None)
    interpreted = getattr(arguments, "interpreter", False)
    if path and not interpreted:
        raise SithError("--namespaces requires --interpreter")
    return Namespaces.load(path) if interpreted and path else Namespaces()
