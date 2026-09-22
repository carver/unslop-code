"""The project configuration file, `.sith/project.json`.

The file records which interpreter a project uses and how imports are
resolved in it. `project init` writes it; every other command reads whatever
it finds in the project root.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

from .source import SourceError

CONFIG_DIRECTORY = ".sith"
CONFIG_NAME = "project.json"

DEFAULTS = {
    "environment_path": "",
    "sys_path": [],
    "added_sys_path": [],
    "smart_sys_path": True,
}


@dataclass(frozen=True)
class ProjectConfig:
    """What the configuration file of a project says.

    An `environment_path` of `None` and one of `""` mean the same thing - use
    the system default - so both are read as the empty string.
    """

    environment_path: str = ""
    sys_path: Tuple[str, ...] = ()
    added_sys_path: Tuple[str, ...] = ()
    smart_sys_path: bool = True


def config_file(root) -> Path:
    """Where a project keeps its configuration."""
    return Path(root) / CONFIG_DIRECTORY / CONFIG_NAME


def load_config(root) -> ProjectConfig:
    """The configuration of a project, or the defaults when it has none."""
    written = read_document(config_file(root))
    return ProjectConfig(
        environment_path=written.get("environment_path") or "",
        sys_path=tuple(written.get("sys_path") or ()),
        added_sys_path=tuple(written.get("added_sys_path") or ()),
        smart_sys_path=bool(written.get("smart_sys_path", True)),
    )


def read_document(path: Path) -> Dict:
    """The configuration file as it was written, empty when there is none."""
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise SourceError(f"cannot read {path}: {error}") from error


def initialize(directory, updates: Dict) -> Dict:
    """Create or update the configuration of a project, and return it.

    Fields the command line did not mention keep the value they already had,
    and fields the file never carried take their default.
    """
    path = config_file(directory)
    document = {**DEFAULTS, **read_document(path), **updates}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return document
