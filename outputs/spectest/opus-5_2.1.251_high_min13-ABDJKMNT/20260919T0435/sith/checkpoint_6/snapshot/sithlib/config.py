"""The project configuration file, `.sith/project.json`.

The file records which interpreter a project uses and where its imports are
looked for.  It is written by `project init` and read by every command, whose
own `--setting` flags take precedence over what it says.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from . import project, settings
from .source import SithError

DIRECTORY = ".sith"
FILE = "project.json"

#: The configuration a project has before anything is written into it.
DEFAULTS = {
    "environment_path": "",
    "sys_path": [],
    "added_sys_path": [],
    "smart_sys_path": True,
}


@dataclass(frozen=True)
class ProjectConfig:
    """What the configuration of one project root says, with defaults applied."""

    root: str
    environment_path: str = ""
    sys_path: tuple[str, ...] = ()
    added_sys_path: tuple[str, ...] = ()
    #: The `--setting` names the file overrides, as `(name, value)` pairs.
    settings: tuple[tuple[str, bool], ...] = ()

    @classmethod
    def load(cls, root: str) -> "ProjectConfig":
        stored = read(root)
        return cls(
            root=root,
            environment_path=stored.get("environment_path") or "",
            sys_path=tuple(stored.get("sys_path") or ()),
            added_sys_path=tuple(stored.get("added_sys_path") or ()),
            settings=tuple(
                (name, value)
                for name, value in stored.items()
                if name in settings.NAMES and isinstance(value, bool)
            ),
        )

    def search_paths(self, smart: bool) -> list[str]:
        """Where imports are looked for: the configured roots, then the added ones.

        An explicit `sys_path` replaces what `smart_sys_path` would detect, and
        `added_sys_path` is appended to whichever of the two is in force.
        """
        explicit = [self.absolute(entry) for entry in self.sys_path]
        detected = explicit or (project.import_roots(self.root) if smart else [])
        added = [self.absolute(entry) for entry in self.added_sys_path]
        return list(dict.fromkeys(detected + added))

    def absolute(self, entry: str) -> str:
        """A configured path, read relative to the project root unless absolute."""
        return os.path.normpath(os.path.join(self.root, entry))


def path_of(root: str) -> str:
    return os.path.join(root, DIRECTORY, FILE)


def read(root: str) -> dict:
    """The stored configuration of a project root; an empty one when it has none."""
    try:
        text = open(path_of(root), "rb").read().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    try:
        stored = json.loads(text)
    except ValueError as error:
        raise SithError(f"invalid project configuration {path_of(root)}: {error}") from error
    if not isinstance(stored, dict):
        raise SithError(f"invalid project configuration {path_of(root)}: not an object")
    return stored


def initialize(directory: str | None, environment: str | None, sys_path: str | None,
               added_sys_path: str | None) -> dict:
    """Create or update the configuration of a project, keeping what was not passed."""
    root = os.path.abspath(directory or os.curdir)
    written = {**DEFAULTS, **read(root), **_passed(environment, sys_path, added_sys_path)}
    os.makedirs(os.path.dirname(path_of(root)), exist_ok=True)
    with open(path_of(root), "w", encoding="utf-8") as handle:
        json.dump(written, handle, indent=2)
        handle.write("\n")
    return written


def _passed(environment: str | None, sys_path: str | None, added_sys_path: str | None) -> dict:
    """The fields the command line set; a flag left out leaves its field alone."""
    given = {
        "environment_path": environment,
        "sys_path": _entries(sys_path),
        "added_sys_path": _entries(added_sys_path),
    }
    return {name: value for name, value in given.items() if value is not None}


def _entries(text: str | None) -> list[str] | None:
    """A `--sys-path a,b` flag as a list; not passing the flag is not an empty list."""
    return [entry for entry in text.split(",") if entry] if text is not None else None
