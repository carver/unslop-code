"""Schema inference from the inputs themselves, used when --schema is absent.

Every input is scanned once. For each file a column is reduced to the set of
types that fit all of its observed values; the two ``--infer`` modes then
combine those per-file sets differently.
"""

from __future__ import annotations

from .casting import PRIORITY, TYPES, best_type
from .reader import CsvFormat, open_table
from .schema import Schema, schema_from_types

_ALL_TYPES = frozenset(PRIORITY)
_STRING_ONLY = frozenset({"string"})


def infer_schema(paths, fmt: CsvFormat, mode: str) -> Schema:
    """Resolve a schema from the union of the input headers and their values."""
    names: set[str] = set()
    per_file = []
    for path in paths:
        with open_table(path, fmt) as (header, rows):
            names.update(header)
            per_file.append(_scan_file(header, rows, fmt, mode))

    resolve = _resolve_strict if mode == "strict" else _resolve_loose
    return schema_from_types((name, resolve(name, per_file)) for name in sorted(names))


def _scan_file(header, rows, fmt: CsvFormat, mode: str) -> dict[str, frozenset]:
    """Narrow each column of one file to the types all its values fit."""
    feasible: dict[str, frozenset] = {}
    for row in rows:
        for name, text in zip(header, row):
            candidates = feasible.get(name, _ALL_TYPES)
            if candidates == _STRING_ONLY:
                continue
            if fmt.is_null(text):
                # In loose mode nulls say nothing about the type; in strict mode
                # they are an observed value that only the string type accepts.
                if mode == "strict":
                    feasible[name] = _STRING_ONLY
            else:
                feasible[name] = frozenset(t for t in candidates if TYPES[t].recognize(text))
    return feasible


def _resolve_strict(name: str, per_file) -> str:
    """Each file votes with its own inferred type; disagreement means string."""
    votes = {best_type(feasible[name]) for feasible in per_file if name in feasible}
    return votes.pop() if len(votes) == 1 else "string"


def _resolve_loose(name: str, per_file) -> str:
    """Take the best type that fits the non-null values of every file at once."""
    observed = [feasible[name] for feasible in per_file if name in feasible]
    if not observed:
        return "string"
    return best_type(frozenset.intersection(*observed))
