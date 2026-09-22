"""The runtime namespaces interpreter mode falls back to.

A namespaces file describes what a live session holds: a JSON array of
objects, each mapping a name to a record of what the running interpreter
found there. Static analysis always answers first; these values only stand in
for the names source alone cannot explain.
"""

import json
from dataclasses import dataclass

from . import symbols
from .definitions import Definition
from .errors import SithError


@dataclass(frozen=True)
class NamespaceValue:
    """A value known from a running interpreter rather than from source.

    `key` is the name the session binds it to, `text` the printed value the
    namespace recorded, and `origin` the name it goes by inside `module`.
    """

    key: str
    type_name: str
    text: str = ""
    module: str = ""
    origin: str = ""
    attributes: tuple = ()

    def definition(self):
        """The record printed for a name only the interpreter knows about."""
        return Definition(
            name=self.key,
            type=self.type_name,
            full_name=self._full_name(),
            module_path="",
            line=0,
            column=0,
            description=f"{self.type_name} (runtime)",
            docstring=self.text,
        )

    def _full_name(self):
        """Where the value comes from: its module, then the name it has there."""
        name = self.origin or self.key
        if not self.module or self.module == name:
            return name
        return f"{self.module}.{name}"

    def members(self):
        """Name -> entry for the attributes the namespace recorded, if any."""
        return {name: NamespaceValue(name, symbols.INSTANCE) for name in self.attributes}


def load_namespaces(path):
    """Name -> value for the namespaces a file declares, earliest one winning.

    Namespaces are searched in the order they are written, so a name a later
    namespace also holds does not displace the one already found.
    """
    merged = {}
    for namespace in _namespaces(path):
        for key, record in namespace.items():
            merged.setdefault(key, _value(key, record, path))
    return merged


def _namespaces(path):
    """The namespace objects a file holds, rejecting anything shaped otherwise."""
    try:
        with open(path, encoding="utf-8") as handle:
            declared = json.load(handle)
    except OSError:
        raise SithError(f"cannot read namespaces file: {path}") from None
    except json.JSONDecodeError as error:
        raise SithError(f"invalid namespaces file: {path}: {error}") from None
    if not isinstance(declared, list) or not all(isinstance(item, dict) for item in declared):
        raise SithError(f"invalid namespaces file: {path}: expected an array of objects")
    return declared


def _value(key, record, path):
    """One namespace entry, which must at least say what type the value has."""
    if not isinstance(record, dict) or not isinstance(record.get("type"), str):
        raise SithError(f"invalid namespaces file: {path}: {key} needs a type")
    return NamespaceValue(
        key=key,
        type_name=record["type"],
        text=str(record.get("value", "")),
        module=record.get("module", ""),
        origin=record.get("name", ""),
        attributes=tuple(record.get("attributes", ())),
    )
