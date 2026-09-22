"""Finding the Python installations of the machine and describing them.

An environment is described by asking it: the candidate is run with a one line
program that prints what it is.  Anything that cannot answer -- a broken
symlink, a program that is not Python at all -- is simply not an environment.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from .errors import SithError

_PROBE = (
    "import json, sys;"
    "print(json.dumps({'version': '.'.join(str(part) for part in sys.version_info[:3]),"
    " 'prefix': sys.prefix, 'base': getattr(sys, 'base_prefix', sys.prefix),"
    " 'executable': sys.executable, 'path': sys.path}))"
)
_TIMEOUT = 15
_EXECUTABLE = re.compile(r"^python(\d+(\.\d+)?)?(\.exe)?$")
_LAYOUTS = ("bin/python", "Scripts/python.exe")


@dataclass(frozen=True)
class Environment:
    """One Python installation, as ``env`` reports it."""

    executable: str
    version: str
    is_virtualenv: bool
    prefix: str
    sys_path: tuple[str, ...]

    def as_dict(self, detailed: bool = False) -> dict[str, object]:
        """The listing fields, plus the ones ``env info`` adds when detailed."""
        listing: dict[str, object] = {"executable": self.executable, "version": self.version,
                                      "is_virtualenv": self.is_virtualenv}
        if not detailed:
            return listing
        return {**listing, "prefix": self.prefix, "sys_path": list(self.sys_path)}


def describe(executable: str) -> Environment | None:
    """What ``executable`` is, or ``None`` when it is not a usable Python."""
    try:
        result = subprocess.run([executable, "-c", _PROBE], capture_output=True, text=True,
                                timeout=_TIMEOUT)
        reported = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None
    return Environment(reported["executable"], reported["version"],
                       reported["prefix"] != reported["base"], reported["prefix"],
                       tuple(reported["path"]))


def info(executable: str | None, config_environment: str) -> Environment:
    """The environment ``env info`` was asked about; failing to find one is an error."""
    wanted = executable or config_environment or "python3"
    found = describe(wanted)
    if found is None:
        raise SithError(f"not a usable Python environment: {wanted}")
    return found


def installations(root: Path) -> list[Environment]:
    """Every Python the machine offers: those on the path and those in virtualenvs."""
    return _described([*_on_path(), *_virtualenv_candidates(None, root), sys.executable])


def virtualenvs(path: Path | None, root: Path) -> list[Environment]:
    """The virtualenvs of ``path``, of ``~/.virtualenvs`` and of the project."""
    found = _described(_virtualenv_candidates(path, root))
    return [environment for environment in found if environment.is_virtualenv]


def _described(candidates: Iterable[str]) -> list[Environment]:
    """Describe each candidate once, newest version first.

    Two paths naming the same interpreter of the same prefix are the same
    environment; a virtualenv shares its interpreter with the installation it
    was made from, and its prefix is what tells the two apart.
    """
    found: dict[tuple[str, str], Environment] = {}
    for candidate in dict.fromkeys(candidates):
        environment = describe(candidate)
        if environment is not None:
            key = (str(Path(environment.executable).resolve()), environment.prefix)
            found.setdefault(key, environment)
    return sorted(found.values(), key=_order)


def _order(environment: Environment) -> tuple[tuple[int, ...], str]:
    """Newest version first, then by path."""
    return tuple(-int(part) for part in environment.version.split(".")), environment.executable


def _on_path() -> Iterator[str]:
    """Everything named like a Python interpreter on ``PATH``."""
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        entries = sorted(Path(directory).glob("python*")) if directory else []
        yield from (str(entry) for entry in entries if _EXECUTABLE.match(entry.name))


def _virtualenv_candidates(path: Path | None, root: Path) -> Iterator[str]:
    """Where virtualenvs are conventionally kept, in the order they are searched."""
    directories = [path] if path is not None else []
    directories.append(Path.home() / ".virtualenvs")
    for directory in directories:
        yield from (str(found) for child in _subdirectories(directory)
                    if (found := _interpreter(child)) is not None)
    for directory in dict.fromkeys((Path.cwd(), root)):
        yield from (str(found) for name in (".venv", "venv")
                    if (found := _interpreter(directory / name)) is not None)


def _subdirectories(directory: Path) -> list[Path]:
    """The immediate subdirectories of ``directory``, in name order."""
    if not directory.is_dir():
        return []
    return sorted(child for child in directory.iterdir() if child.is_dir())


def _interpreter(directory: Path) -> Path | None:
    """The interpreter a virtualenv directory holds, whatever the platform."""
    candidates = (directory / layout for layout in _LAYOUTS)
    return next((path for path in candidates if path.is_file()), None)
