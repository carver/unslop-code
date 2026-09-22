"""Finding the Python interpreters this machine offers, and describing them.

An interpreter can only describe itself, so every candidate is asked: it
reports its version, its prefix and its `sys.path` in one go, and whatever
cannot answer is not a Python and is dropped.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass

from .source import SithError

#: The interpreter of a virtualenv, wherever the host keeps it.
INTERPRETER = ("Scripts", "python.exe") if os.name == "nt" else ("bin", "python")

#: Where virtualenvs are looked for besides the directory a request names.
VIRTUALENVS = "~/.virtualenvs"
VENV_NAMES = (".venv", "venv")

DEFAULT_PYTHON = "python3"
PROBE = (
    "import json,sys;"
    "print(json.dumps(['.'.join(map(str, sys.version_info[:3])),"
    " sys.prefix, sys.base_prefix, sys.path]))"
)
PROBE_TIMEOUT = 15

_PYTHON_NAME = re.compile(r"python(\d+(\.\d+)?)?(\.exe)?", re.IGNORECASE)


@dataclass(frozen=True)
class Environment:
    """One Python installation, as it describes itself."""

    executable: str
    version: str
    prefix: str
    is_virtualenv: bool
    sys_path: tuple[str, ...]

    def as_dict(self, full: bool = False) -> dict:
        """The listed fields, or those plus what `env info` adds."""
        record = {
            "executable": self.executable,
            "version": self.version,
            "is_virtualenv": self.is_virtualenv,
        }
        if not full:
            return record
        return {**record, "prefix": self.prefix, "sys_path": list(self.sys_path)}


def installed(root: str) -> list[dict]:
    """Every Python installation found on the search path and in the usual places."""
    found = probed([*_on_path(), sys.executable, *_virtualenv_interpreters(None, root)])
    return [environment.as_dict() for environment in ordered(unique(found))]


def virtualenvs(path: str | None, root: str) -> list[dict]:
    """The virtualenvs of the standard locations, and of a directory if one is named.

    Each virtualenv is one environment of its own even when several were built
    from -- and so resolve to -- the same interpreter.
    """
    found = probed(_virtualenv_interpreters(path, root))
    return [environment.as_dict() for environment in ordered(found) if environment.is_virtualenv]


def details(executable: str) -> dict:
    """Everything one environment knows about itself, the system default by default."""
    wanted = executable or DEFAULT_PYTHON
    found = probe(_locate(wanted))
    if found is None:
        raise SithError(f"not a Python interpreter: {wanted}")
    return found.as_dict(full=True)


def probe(executable: str) -> Environment | None:
    """Ask an executable to describe itself, or None when it is not an interpreter."""
    try:
        result = subprocess.run(
            [executable, "-c", PROBE], capture_output=True, text=True, timeout=PROBE_TIMEOUT
        )
        version, prefix, base_prefix, search_path = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return Environment(executable, version, prefix, prefix != base_prefix, tuple(search_path))


def probed(candidates: list[str]) -> list[Environment]:
    """Describe each candidate once, dropping whatever does not answer."""
    wanted = dict.fromkeys(os.path.abspath(path) for path in candidates)
    found = (probe(path) for path in wanted)
    return [environment for environment in found if environment is not None]


def ordered(found: list[Environment]) -> list[Environment]:
    """Newest first, and paths in order among environments of the same version."""
    by_path = sorted(found, key=lambda environment: environment.executable)
    return sorted(by_path, key=lambda environment: _version(environment.version), reverse=True)


def unique(found: list[Environment]) -> list[Environment]:
    """One entry per installation: two names for one file are one Python."""
    distinct: dict[str, Environment] = {}
    for environment in found:
        distinct.setdefault(os.path.realpath(environment.executable), environment)
    return list(distinct.values())


def _version(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split(".") if part.isdigit())


def _locate(executable: str) -> str:
    """A bare name is looked for on the search path; a path is taken as written."""
    if os.path.dirname(executable):
        return os.path.abspath(executable)
    return shutil.which(executable) or executable


def _on_path() -> list[str]:
    """Every file on the search path named the way an interpreter is named."""
    return [
        entry.path
        for directory in os.get_exec_path()
        for entry in _entries(directory)
        if _PYTHON_NAME.fullmatch(entry.name) and os.access(entry.path, os.X_OK)
    ]


def _virtualenv_interpreters(path: str | None, root: str) -> list[str]:
    """The interpreters of the virtualenvs a search is allowed to look at.

    A directory named by `--path` and `~/.virtualenvs` hold one virtualenv per
    subdirectory; the current directory and the project root hold theirs under
    a conventional name.
    """
    directories = [*_subdirectories(path), *_subdirectories(os.path.expanduser(VIRTUALENVS))]
    for base in dict.fromkeys([os.path.abspath(os.curdir), root]):
        directories += [os.path.join(base, name) for name in VENV_NAMES]
    interpreters = (os.path.join(directory, *INTERPRETER) for directory in directories)
    return [path for path in interpreters if os.path.isfile(path)]


def _subdirectories(directory: str | None) -> list[str]:
    return [entry.path for entry in _entries(directory) if entry.is_dir()] if directory else []


def _entries(directory: str | None) -> list[os.DirEntry]:
    """What a directory holds, in name order; nothing when it cannot be read."""
    try:
        return sorted(os.scandir(directory), key=lambda entry: entry.name)
    except OSError:
        return []
