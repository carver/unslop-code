"""Finding and describing the Python environments installed on a machine.

An environment is interrogated by running it: the interpreter reports its own
version, prefix and search path. A virtualenv whose interpreter cannot be run
is still described by the `pyvenv.cfg` file that makes it one.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from .definitions import document
from .source import SourceError

PROBE = (
    "import json,sys;"
    "print(json.dumps({"
    "'version':'.'.join(str(part) for part in sys.version_info[:3]),"
    "'is_virtualenv':sys.prefix!=sys.base_prefix,"
    "'prefix':sys.prefix,'sys_path':sys.path}))"
)
PROBE_TIMEOUT = 20

INTERPRETER_NAME = re.compile(r"python(\d+(\.\d+)?)?(\.exe)?", re.IGNORECASE)
INTERPRETERS = (Path("bin", "python"), Path("Scripts", "python.exe"))
"""Where a virtualenv keeps its interpreter, on Unix and on Windows."""

VENV_CONFIG = "pyvenv.cfg"
VIRTUALENVS = ".virtualenvs"
VENV_DIRECTORIES = (".venv", "venv")
DEFAULT_EXECUTABLE = "python3"


@dataclass(frozen=True)
class Environment:
    """One Python environment, as the commands report it."""

    executable: str
    version: str
    is_virtualenv: bool
    prefix: str = ""
    sys_path: Tuple[str, ...] = ()

    def listed(self) -> Dict:
        """The fields `env list` and `env find-virtualenvs` report."""
        return {
            "executable": self.executable,
            "version": self.version,
            "is_virtualenv": self.is_virtualenv,
        }

    def detailed(self) -> Dict:
        """The fields `env info` reports, which say where the environment is."""
        return {**self.listed(), "prefix": self.prefix, "sys_path": list(self.sys_path)}


# --------------------------------------------------------------------------
# Describing one environment
# --------------------------------------------------------------------------


def describe(executable: Path) -> Optional[Environment]:
    """What an interpreter says about itself, or what its virtualenv does."""
    reported = interrogate(executable)
    if reported is not None:
        return reported
    return _configured(executable)


def interrogate(executable: Path) -> Optional[Environment]:
    """Run an interpreter to read its version, prefix and search path."""
    try:
        finished = subprocess.run(
            [str(executable), "-c", PROBE],
            capture_output=True, text=True, timeout=PROBE_TIMEOUT,
        )
        reported = json.loads(finished.stdout) if finished.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if reported is None:
        return None
    return Environment(
        executable=str(executable),
        version=reported["version"],
        is_virtualenv=reported["is_virtualenv"],
        prefix=reported["prefix"],
        sys_path=tuple(reported["sys_path"]),
    )


def _configured(executable: Path) -> Optional[Environment]:
    """A virtualenv described by its `pyvenv.cfg` rather than by running it."""
    root = executable.parent.parent
    config = _read_config(root / VENV_CONFIG)
    if config is None:
        return None
    return Environment(
        executable=str(executable),
        version=config.get("version", config.get("version_info", "")),
        is_virtualenv=True,
        prefix=str(root),
    )


def _read_config(path: Path) -> Optional[Dict[str, str]]:
    """The `key = value` lines of a `pyvenv.cfg`, or ``None`` if it has none."""
    if not path.is_file():
        return None
    written = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        key, separator, value = line.partition("=")
        if separator:
            written[key.strip()] = value.strip()
    return written


# --------------------------------------------------------------------------
# Finding environments
# --------------------------------------------------------------------------


def installations(root: Path) -> List[Environment]:
    """Every Python installation the machine offers, newest first."""
    candidates = [Path(sys.executable), *_on_path(), *_virtualenv_interpreters(None, root)]
    return ordered(found for found in map(describe, candidates) if found is not None)


def virtualenvs(path: Optional[str], root: Path) -> List[Environment]:
    """The virtualenvs found in the standard locations, newest first."""
    described = map(describe, _virtualenv_interpreters(path, root))
    return ordered(found for found in described if found is not None and found.is_virtualenv)


def _on_path() -> Iterator[Path]:
    """Interpreters named `python`, `python3` or `python3.11` on `PATH`."""
    for directory in os.get_exec_path():
        entries = sorted(Path(directory).iterdir()) if Path(directory).is_dir() else []
        for entry in entries:
            if INTERPRETER_NAME.fullmatch(entry.name) and os.access(entry, os.X_OK):
                yield entry


def _virtualenv_interpreters(path: Optional[str], root: Path) -> Iterator[Path]:
    """The interpreters of the directories virtualenvs are looked for in."""
    for directory in _virtualenv_directories(path, root):
        found = next((directory / name for name in INTERPRETERS if (directory / name).exists()), None)
        if found is not None:
            yield found


def _virtualenv_directories(path: Optional[str], root: Path) -> Iterator[Path]:
    """Where the spec looks for virtualenvs, in the order it looks."""
    yield from _subdirectories(Path(path) if path else None)
    yield from _subdirectories(Path.home() / VIRTUALENVS)
    for directory in (Path.cwd(), root):
        for name in VENV_DIRECTORIES:
            yield directory / name


def _subdirectories(directory: Optional[Path]) -> List[Path]:
    """The immediate subdirectories of a directory, in name order."""
    if directory is None or not directory.is_dir():
        return []
    return sorted(child for child in directory.iterdir() if child.is_dir())


def ordered(found) -> List[Environment]:
    """Environments newest first, then by path, one per resolved executable."""
    ranked = sorted(found, key=lambda environment: (
        _version_key(environment.version), environment.executable
    ))
    kept: Dict[str, Environment] = {}
    for environment in ranked:
        kept.setdefault(str(Path(environment.executable).resolve()), environment)
    return list(kept.values())


def _version_key(version: str) -> Tuple[int, ...]:
    """Sort key placing newer versions first and unknown ones last."""
    parts = [int(part) for part in version.split(".") if part.isdigit()]
    return tuple(-part for part in parts) if parts else (0,)


# --------------------------------------------------------------------------
# The answers of the `env` subcommands
# --------------------------------------------------------------------------


def listing(found: List[Environment]) -> str:
    """The JSON document `env list` and `env find-virtualenvs` write."""
    return document(environments=[environment.listed() for environment in found])


def details(executable: Optional[str]) -> str:
    """The JSON document `env info` writes, for the interpreter it names."""
    wanted = executable or DEFAULT_EXECUTABLE
    located = _located(wanted)
    found = interrogate(located) if located is not None else None
    if found is None:
        raise SourceError(f"not a Python environment: {wanted}")
    return document(**found.detailed())


def _located(executable: str) -> Optional[Path]:
    """The interpreter a name or a path refers to, looked up on `PATH`."""
    found = shutil.which(executable)
    if found is not None:
        return Path(found)
    return Path(executable) if Path(executable).is_file() else None
