"""The definition records that ``infer`` and ``goto`` report.

A record says where a name was written down and how it should be described.
Names that come from outside the project -- builtins and installed packages --
have no position to report, so their path is empty and their line and column
are zero.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable


@dataclass(frozen=True)
class Definition:
    """One entry of the JSON output of ``infer`` and ``goto``."""

    name: str
    type: str
    full_name: str
    module_path: str
    line: int
    column: int
    description: str
    docstring: str = ""

    def as_dict(self, docstring: bool = True) -> dict[str, object]:
        """The record as JSON; ``search`` reports everything but the docstring."""
        fields = asdict(self)
        if not docstring:
            fields.pop("docstring")
        return fields


def ordered(definitions: Iterable[Definition]) -> list[Definition]:
    """Unique definitions in reporting order: by path, then line, then column."""
    unique = dict.fromkeys(definitions)
    return sorted(unique, key=lambda definition: (definition.module_path, definition.line,
                                                  definition.column))
