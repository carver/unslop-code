"""Resolving the output schema, either from a JSON file or by inference.

With ``--schema`` the file is the schema: it fixes the output columns, their
types and their order, nested types included.  Otherwise every input is scanned, the columns are the
union of the names seen in lexicographic order, and each column's type is
settled by ``--schema-strategy``:

``authoritative``
    the inputs that carry the most type information decide.  Parquet outranks
    CSV and JSON Lines, which rank equally, which in turn outrank TSV.
``consensus``
    the type most inputs infer for the column wins.
``union``
    the most specific type that can hold every value of every input wins.

Where a strategy has to settle a disagreement it follows ``--infer``: ``strict``
falls back to ``string`` unless the inputs agree, ``loose`` widens to the type
that holds them all.  ``union`` is widening by definition, so ``--infer`` does
not apply to it.

Inference is flat: an input that holds an array or an object is rejected
unless ``--schema`` declares what it should be cast to.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

from casting import ValueType
from column_types import TYPES, best_type
from errors import SchemaError
from inference import Candidates
from sources import Reader
from type_specs import TypeAliases, parse_type

# What the inputs holding one column say about it: each input's format and the
# types that column is compatible with there.
Observations = list[tuple[str, set[str]]]

# How much type information a format carries.  Parquet declares its types;
# JSON Lines values are typed but its strings are as untyped as a CSV cell; TSV
# has neither quoting nor types, so it is the weakest voice.
_PRECEDENCE = {"parquet": 2, "csv": 1, "jsonl": 1, "tsv": 0}


@dataclass(frozen=True)
class Column:
    """One column of the resolved output schema."""

    name: str
    type: ValueType


def declared_types(columns: Sequence[Column]) -> dict[str, ValueType]:
    """The type of each column, for resolving the field paths against."""
    return {column.name: column.type for column in columns}


def load_schema(path: Path, aliases: TypeAliases) -> list[Column]:
    """Read an explicit schema: ``{"columns": [{"name": ..., "type": ...}]}``.

    A column's type is a name, a generic or the object form of a nested type;
    :mod:`type_specs` builds it, aliases included.
    """
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SchemaError(f"{path}: invalid JSON ({error})") from error
    entries = document.get("columns") if isinstance(document, dict) else None
    if not isinstance(entries, list):
        raise SchemaError(f"{path}: schema must be an object with a 'columns' list")

    columns = []
    for entry in entries:
        name, spec = entry.get("name"), entry.get("type")
        if not name or spec is None:
            raise SchemaError(f"{path}: every schema column needs a 'name' and a 'type'")
        columns.append(Column(name, parse_type(spec, aliases, name)))
    return columns


def infer_schema(readers: Sequence[Reader], mode: str, strategy: str) -> list[Column]:
    """Infer the schema from the union of the columns of every input.

    Columns are ordered lexicographically.  A column that no input ever
    populates is a string, since nothing narrows it.
    """
    scans = [(reader.format, reader.scan()) for reader in readers]
    names = sorted({name for _format, candidates in scans for name in candidates})
    choose = _STRATEGIES[strategy]
    columns = []
    for name in names:
        observed = _observations(scans, name)
        type_name = choose(observed, mode) if observed else "string"
        columns.append(Column(name, TYPES[type_name]))
    return columns


def _observations(scans: list[tuple[str, Candidates]], name: str) -> Observations:
    return [(fmt, types) for fmt, candidates in scans if (types := candidates.get(name))]


def _authoritative(observed: Observations, mode: str) -> str:
    """Let the formats that carry the most type information decide."""
    rank = max(_PRECEDENCE[fmt] for fmt, _types in observed)
    return _reconcile([types for fmt, types in observed if _PRECEDENCE[fmt] == rank], mode)


def _consensus(observed: Observations, mode: str) -> str:
    """Take the type most inputs infer, reconciling only a tie."""
    votes = Counter(best_type(types) for _fmt, types in observed)
    leading = max(votes.values())
    leaders = {name for name, count in votes.items() if count == leading}
    if len(leaders) == 1:
        return leaders.pop()
    return _reconcile([types for _fmt, types in observed if best_type(types) in leaders], mode)


def _union(observed: Observations, _mode: str) -> str:
    """Take the most specific type that can hold every value of every input."""
    return _widen([types for _fmt, types in observed])


def _reconcile(candidates: Sequence[set[str]], mode: str) -> str:
    """Settle a disagreement between inputs the way ``--infer`` asks for."""
    if mode == "loose":
        return _widen(candidates)
    agreed = {best_type(types) for types in candidates}
    return agreed.pop() if len(agreed) == 1 else "string"


def _widen(candidates: Iterable[set[str]]) -> str:
    """The most specific type every one of ``candidates`` allows."""
    return best_type(set.intersection(*candidates))


_STRATEGIES: dict[str, Callable[[Observations, str], str]] = {
    "authoritative": _authoritative,
    "consensus": _consensus,
    "union": _union,
}

STRATEGIES = tuple(_STRATEGIES)
