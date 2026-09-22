"""The configuration a project keeps in ``.sith/project.json``.

The file says which interpreter a project belongs to and where its imports
should be looked for.  It is read by every command and written only by
``project init``, which merges the flags it was given into whatever is already
there.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from .errors import SithError

DIRECTORY = ".sith"
FILENAME = "project.json"


@dataclass(frozen=True)
class ProjectConfig:
    """What ``.sith/project.json`` declares, with the defaults of an absent file."""

    environment_path: str = ""
    sys_path: tuple[str, ...] = ()
    added_sys_path: tuple[str, ...] = ()
    smart_sys_path: bool = True

    @staticmethod
    def path(root: Path) -> Path:
        return root / DIRECTORY / FILENAME

    @classmethod
    def load(cls, root: Path) -> "ProjectConfig":
        """The configuration of the project rooted at ``root``, defaults if it has none."""
        path = cls.path(root)
        if not path.is_file():
            return cls()
        try:
            declared = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SithError(f"not a valid project configuration: {path} ({error})") from error
        if not isinstance(declared, dict):
            raise SithError(f"expected a JSON object in {path}")
        return cls(declared.get("environment_path") or "",
                   tuple(declared.get("sys_path") or ()),
                   tuple(declared.get("added_sys_path") or ()),
                   bool(declared.get("smart_sys_path", True)))

    def merged(self, **changes: object) -> "ProjectConfig":
        """This configuration with the fields that were explicitly given replaced."""
        return replace(self, **{name: value for name, value in changes.items()
                                if value is not None})

    def write(self, root: Path) -> Path:
        """Store the configuration under ``root``, creating ``.sith/`` if needed."""
        path = self.path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.as_dict(), indent=2) + "\n", encoding="utf-8")
        return path

    def as_dict(self) -> dict[str, object]:
        fields = asdict(self)
        return {name: list(value) if isinstance(value, tuple) else value
                for name, value in fields.items()}
