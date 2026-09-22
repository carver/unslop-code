"""The project file a run is configured by, and the settings it can turn.

A project keeps its configuration in ``.sith/project.json`` at its root. The
file says which interpreter the project uses, which directories imports are
resolved against, and may carry any of the settings ``--setting`` overrides.
"""

import json
import os
from dataclasses import dataclass, field, fields

from .errors import SithError

CONFIG_DIRECTORY = ".sith"
CONFIG_NAME = "project.json"


@dataclass(frozen=True)
class Settings:
    """The behaviour a run can be asked for, by flag or by project file."""

    case_insensitive: bool = True
    dynamic_params: bool = True
    smart_sys_path: bool = True
    add_bracket: bool = False


@dataclass(frozen=True)
class ProjectConfig:
    """What the project file declares, with the defaults for what it omits.

    `settings` holds the setting keys the file carries, which the command
    line is free to override.
    """

    environment_path: str = ""
    sys_path: tuple = ()
    added_sys_path: tuple = ()
    settings: dict = field(default_factory=dict)


_SETTING_NAMES = tuple(declared.name for declared in fields(Settings))

_DEFAULT_RECORD = {
    "environment_path": "",
    "sys_path": [],
    "added_sys_path": [],
    "smart_sys_path": True,
}


def config_path(root):
    """Where the project file of a project rooted at `root` is stored."""
    return os.path.join(root, CONFIG_DIRECTORY, CONFIG_NAME)


def load_config(root):
    """The configuration of the project at `root`, defaulted when it has none."""
    stored = _stored(config_path(root))
    return ProjectConfig(
        environment_path=stored.get("environment_path") or "",
        sys_path=tuple(stored.get("sys_path", ())),
        added_sys_path=tuple(stored.get("added_sys_path", ())),
        settings={name: stored[name] for name in _SETTING_NAMES if name in stored},
    )


def initialise(root, updates):
    """Write the project file of `root`, merging `updates` into what it holds.

    Only the fields the command line passed are updated; everything else keeps
    the value the file already carried, or the default when it carried none.
    """
    record = {**_DEFAULT_RECORD, **_stored(config_path(root)), **updates}
    os.makedirs(os.path.join(root, CONFIG_DIRECTORY), exist_ok=True)
    with open(config_path(root), "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2)
        handle.write("\n")
    return record


def settings_for(config, overrides):
    """The settings a run uses: the defaults, then the project file, then flags."""
    values = dict(config.settings)
    values.update(_pair(text) for text in overrides)
    return Settings(**{name: _boolean(name, value) for name, value in values.items()})


def search_paths(root, config, settings):
    """The directories absolute imports are resolved against, in search order.

    An explicit ``sys_path`` replaces the paths detection would find;
    ``added_sys_path`` is appended to whichever of the two is in force.
    """
    declared = _absolute(root, config.sys_path)
    if not declared and settings.smart_sys_path:
        declared = [root] + package_directories(root)
    return declared + _absolute(root, config.added_sys_path)


def package_directories(root):
    """The directories inside a project that hold an ``__init__.py``."""
    found = []
    for directory, inside, files in os.walk(root):
        inside[:] = sorted(name for name in inside
                           if not name.startswith(".") and name != "__pycache__")
        if "__init__.py" in files:
            found.append(directory)
    return found


def _stored(path):
    """The raw record a project file holds, or an empty one when it has none."""
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        try:
            record = json.load(handle)
        except json.JSONDecodeError as error:
            raise SithError(f"invalid project file: {path}: {error}") from None
    if not isinstance(record, dict):
        raise SithError(f"invalid project file: {path}: expected a JSON object")
    return record


def _absolute(root, paths):
    """Configured paths, read relative to the project root unless absolute."""
    return [os.path.abspath(os.path.join(root, path)) for path in paths]


def _pair(text):
    """The name and value of one ``key=value`` setting flag."""
    name, separator, value = text.partition("=")
    if not separator:
        raise SithError(f"settings are written as key=value, not: {text}")
    if name not in _SETTING_NAMES:
        raise SithError(f"unknown setting: {name}")
    return name, value


def _boolean(name, value):
    """A setting value, written as a JSON boolean or as `true`/`false` text."""
    if isinstance(value, bool):
        return value
    spelled = str(value).strip().lower()
    if spelled not in ("true", "false"):
        raise SithError(f"setting {name} takes true or false, not: {value}")
    return spelled == "true"
