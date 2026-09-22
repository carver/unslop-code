"""Finding the Python interpreters a machine has, and what each one holds."""

import json
import os
import re
import shutil
import subprocess
import sys

from .errors import SithError

DEFAULT_EXECUTABLE = "python3"

_PROBE = (
    "import json,sys;"
    "print(json.dumps({'version': '.'.join(str(part) for part in sys.version_info[:3]),"
    "'prefix': sys.prefix, 'base_prefix': sys.base_prefix, 'sys_path': sys.path}))"
)
_TIMEOUT = 15
_PYTHON = re.compile(r"python(\d+(\.\d+)*)?(\.exe)?", re.IGNORECASE)
_INTERPRETERS = (os.path.join("bin", "python"), os.path.join("bin", "python3"),
                 os.path.join("Scripts", "python.exe"))
_VIRTUALENV_NAMES = (".venv", "venv")


def installed(root):
    """Every Python installation that can be found, newest version first."""
    return _listed(_path_executables() + [sys.executable] + virtualenv_executables(None, root))


def virtualenvs(path, root):
    """The virtualenvs stored in the standard locations, newest version first."""
    found = _listed(virtualenv_executables(path, root))
    return [record for record in found if record["is_virtualenv"]]


def details(executable, config):
    """Everything known about one interpreter, including the path it imports from.

    The interpreter is the one named on the command line, else the one the
    project file declares, else the default of the machine.
    """
    chosen = executable or config.environment_path or DEFAULT_EXECUTABLE
    resolved = shutil.which(chosen) or chosen
    probe = _probe(resolved)
    if probe is None:
        raise SithError(f"not a Python executable: {chosen}")
    return {
        **_record(os.path.abspath(resolved), probe),
        "prefix": probe["prefix"],
        "sys_path": probe["sys_path"],
    }


def virtualenv_executables(path, root):
    """The interpreters of the directories virtualenvs are conventionally kept in.

    Those are the subdirectories of an explicitly searched directory and of
    ``~/.virtualenvs``, then the ``.venv`` and ``venv`` directories of the
    working directory and of the project.
    """
    directories = _subdirectories(path) + _subdirectories(os.path.expanduser("~/.virtualenvs"))
    for base in dict.fromkeys(place for place in (os.getcwd(), root) if place is not None):
        directories += [os.path.join(base, name) for name in _VIRTUALENV_NAMES]
    found = (_interpreter(directory) for directory in directories)
    return [executable for executable in found if executable is not None]


def _listed(executables):
    """The records of a set of executables, deduplicated by where they resolve to."""
    records = sorted(
        (record for record in (_described(executable) for executable in executables)
         if record is not None),
        key=lambda record: (_version_key(record["version"]), record["executable"]),
    )
    seen = {}
    for record in records:
        seen.setdefault(os.path.realpath(record["executable"]), record)
    return list(seen.values())


def _described(executable):
    """The record of one executable, or ``None`` when it runs no Python."""
    probe = _probe(executable)
    return None if probe is None else _record(os.path.abspath(executable), probe)


def _record(executable, probe):
    return {
        "executable": executable,
        "version": probe["version"],
        "is_virtualenv": probe["prefix"] != probe["base_prefix"],
    }


def _probe(executable):
    """Ask an executable what it is, or report ``None`` when it cannot answer.

    Candidates are gathered from directory listings, so anything from a dead
    symlink to a program that is not Python at all can turn up here.
    """
    try:
        result = subprocess.run([executable, "-c", _PROBE], capture_output=True,
                                text=True, timeout=_TIMEOUT)
        return json.loads(result.stdout) if result.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _path_executables():
    """The Python executables the directories of ``PATH`` hold."""
    found = []
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        found += [os.path.join(directory, name)
                  for name in _entries(directory) if _PYTHON.fullmatch(name)]
    return [path for path in found if os.access(path, os.X_OK) and not os.path.isdir(path)]


def _subdirectories(path):
    """The immediate subdirectories of a directory, which may not exist."""
    if path is None:
        return []
    inside = (os.path.join(path, name) for name in _entries(path))
    return [directory for directory in inside if os.path.isdir(directory)]


def _entries(directory):
    return sorted(os.listdir(directory)) if os.path.isdir(directory) else []


def _interpreter(directory):
    """The interpreter a virtualenv directory holds, if it holds one."""
    found = (os.path.join(directory, name) for name in _INTERPRETERS)
    return next((path for path in found if os.path.isfile(path)), None)


def _version_key(version):
    """Sort key placing the newest version first."""
    return tuple(-int(part) for part in version.split("."))
