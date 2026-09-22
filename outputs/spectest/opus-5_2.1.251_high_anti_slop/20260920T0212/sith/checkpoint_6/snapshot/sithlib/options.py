"""What a command runs under: its project root, settings and namespaces."""

import os
from dataclasses import dataclass, field

from .config import ProjectConfig, Settings, load_config, search_paths, settings_for
from .errors import SithError
from .namespaces import load_namespaces


@dataclass(frozen=True)
class Options:
    """The project and the behaviour one run of a command is bound to.

    `namespace` is empty outside interpreter mode, which is what makes static
    analysis the only source of answers there.
    """

    root: str
    project: ProjectConfig = field(default_factory=ProjectConfig)
    settings: Settings = field(default_factory=Settings)
    namespace: dict = field(default_factory=dict)

    def search_paths(self):
        """The directories this run resolves absolute imports against."""
        return search_paths(self.root, self.project, self.settings)


def options_for(arguments):
    """The options a parsed command line asks for, reading the project file."""
    root = _root(arguments)
    project = load_config(root)
    return Options(
        root=root,
        project=project,
        settings=settings_for(project, arguments.setting or ()),
        namespace=_namespace(arguments),
    )


def _root(arguments):
    """The project root a command works in, which its project file sits at."""
    if arguments.project is not None:
        return _directory(arguments.project)
    if arguments.directory is not None:
        return _directory(arguments.directory)
    if arguments.file is None:
        return os.getcwd()
    return os.path.dirname(os.path.abspath(arguments.file))


def _namespace(arguments):
    """The runtime names interpreter mode falls back to, empty without them."""
    if arguments.namespaces is None:
        return {}
    if not arguments.interpreter:
        raise SithError("--namespaces needs --interpreter")
    return load_namespaces(arguments.namespaces)


def _directory(path):
    if not os.path.isdir(path):
        raise SithError(f"not a project directory: {path}")
    return os.path.abspath(path)
