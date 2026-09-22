"""Schema inference for runs that do not supply --schema.

The output columns are the union of the input headers in ascending lexicographic
order; their types come from the observed values, with the two modes differing in
how they reconcile evidence:

* ``strict`` types each column per file and falls back to ``string`` when two
  files disagree; an empty cell is an observation that only ``string`` accepts.
* ``loose`` pools the values of every file, skipping nulls, and keeps the most
  specific type that accepts all of them.
"""

from __future__ import annotations

from csvmerge.reader import InputDialect, open_table
from csvmerge.schema import Column, Schema
from csvmerge.types import candidate_types, highest_priority

STRICT = "strict"
LOOSE = "loose"


def infer_schema(paths: list[str], mode: str, dialect: InputDialect) -> Schema:
    """Resolve the output schema from the inputs alone."""
    observations = [_observe(path, dialect, skip_nulls=mode == LOOSE) for path in paths]
    names = sorted({name for candidates in observations for name in candidates})
    resolve = _strict_type if mode == STRICT else _loose_type
    return Schema(tuple(Column(name, resolve(name, observations)) for name in names))


def _observe(
    path: str, dialect: InputDialect, skip_nulls: bool
) -> dict[str, set[str] | None]:
    """Map each column of one file to the types accepted by all its values.

    A column whose values were all skipped maps to ``None``: the file carries no
    evidence about it.
    """
    with open_table(path, dialect) as (header, rows):
        accepted: dict[str, set[str] | None] = {name: None for name in header}
        for row in rows:
            for name, text in zip(header, row):
                if skip_nulls and dialect.is_null(text):
                    continue
                seen = accepted[name]
                candidates = candidate_types(text)
                accepted[name] = candidates if seen is None else seen & candidates
        return accepted


def _strict_type(name: str, observations: list[dict[str, set[str] | None]]) -> str:
    """The type every file agrees on, or ``string`` where they conflict."""
    per_file = {
        highest_priority(candidates)
        for candidates in _evidence(name, observations)
    }
    if len(per_file) == 1:
        return per_file.pop()
    return "string"


def _loose_type(name: str, observations: list[dict[str, set[str] | None]]) -> str:
    """The most specific type accepted by the pooled values of every file."""
    evidence = _evidence(name, observations)
    if not evidence:
        return "string"
    return highest_priority(set.intersection(*evidence))


def _evidence(name: str, observations: list[dict[str, set[str] | None]]) -> list[set[str]]:
    """The candidate sets contributed by the files that actually saw values for `name`."""
    return [
        candidates
        for file_observation in observations
        if (candidates := file_observation.get(name)) is not None
    ]
