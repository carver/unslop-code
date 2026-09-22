"""The definition records the `goto` and `infer` commands print."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Definition:
    """Where a name is defined and what is statically known about it."""

    name: str
    type: str
    full_name: str
    module_path: str
    line: int
    column: int
    description: str
    docstring: str


def as_json(definitions):
    """Definition dicts without duplicates, sorted by (module_path, line, column)."""
    ordered = sorted(
        dict.fromkeys(definitions),
        key=lambda item: (item.module_path, item.line, item.column),
    )
    return [asdict(definition) for definition in ordered]
