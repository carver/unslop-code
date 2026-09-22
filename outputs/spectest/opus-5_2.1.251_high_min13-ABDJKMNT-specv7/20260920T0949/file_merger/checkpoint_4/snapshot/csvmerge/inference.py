"""Schema resolution from the inputs themselves, used when --schema is absent.

Every input is scanned once and reduced to an :class:`Observation`: for each of
its columns, the set of types that every value it holds would fit. Parquet
states that set outright from its own schema; the other formats have it derived
from their values under the ``--infer`` mode. ``--schema-strategy`` then says
how the per-file observations are combined into one output type.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import NamedTuple

from .casting import PRIORITY, TYPES, WIDENING, best_type
from .parquet import declared_types
from .reader import CsvFormat
from .records import cell_text
from .schema import Schema, schema_from_types
from .sources import open_records

_ALL_TYPES = frozenset(PRIORITY)
_STRING_ONLY = frozenset({"string"})

#: Precedence of the source kinds for ``--schema-strategy=authoritative``:
#: parquet is the one source with a declared schema, and JSONL ranks with the
#: text formats rather than above them (see AMBIGUITIES T28).
_TYPED_TIER, _UNTYPED_TIER = 0, 1


@dataclass(frozen=True)
class Observation:
    """What one input says about the columns it carries.

    ``names`` is every column the input has, ``feasible`` only those it held a
    value for: a column that was always null states nothing about its type.
    """

    tier: int
    names: set[str]
    feasible: dict[str, frozenset]


class Vote(NamedTuple):
    """What one input says about one column: its tier and the types that fit."""

    tier: int
    feasible: frozenset


def infer_schema(specs, fmt: CsvFormat, mode: str, strategy: str) -> Schema:
    """Resolve a schema from the union of the inputs' columns and their values."""
    observations = [_observe(spec, fmt, mode) for spec in specs]
    resolve = _STRATEGIES[strategy]
    names = sorted({name for observation in observations for name in observation.names})
    return schema_from_types((name, _column_type(observations, name, resolve, mode)) for name in names)


def _column_type(observations, name: str, resolve, mode: str) -> str:
    """Settle one column's type, or call it a string when nothing was observed."""
    votes = _votes(observations, name)
    return resolve(votes, mode) if votes else "string"


def _votes(observations, name: str) -> list[Vote]:
    """What the inputs carrying ``name`` say about it."""
    return [Vote(o.tier, o.feasible[name]) for o in observations if name in o.feasible]


def _observe(spec, fmt: CsvFormat, mode: str) -> Observation:
    """Reduce one input to the types each of its columns can take."""
    if spec.format == "parquet":
        feasible = {name: WIDENING[type_name] for name, type_name in declared_types(spec).items()}
        return Observation(_TYPED_TIER, set(feasible), feasible)
    return _scan(spec, fmt, mode)


def _scan(spec, fmt: CsvFormat, mode: str) -> Observation:
    """Narrow each column of one input to the types all of its values fit."""
    feasible: dict[str, frozenset] = {}
    with open_records(spec, fmt, nested_ok=False) as stream:
        names = set(stream.names)
        for record in stream.records:
            names.update(record.names)
            for name, cell in zip(record.names, record.values):
                candidates = feasible.get(name, _ALL_TYPES)
                if candidates == _STRING_ONLY:
                    continue
                text = cell_text(cell)
                if text is None:
                    # In loose mode nulls say nothing about the type; in strict
                    # mode they are an observed value only string accepts.
                    if mode == "strict":
                        feasible[name] = _STRING_ONLY
                else:
                    feasible[name] = frozenset(t for t in candidates if TYPES[t].recognize(text))
    return Observation(_UNTYPED_TIER, names, feasible)


def _combine(votes: list[Vote], mode: str) -> str:
    """Merge feasible sets the way ``--infer`` prescribes."""
    if mode == "strict":
        # Each file states its own type; disagreement means string.
        stated = {best_type(vote.feasible) for vote in votes}
        return stated.pop() if len(stated) == 1 else "string"
    return best_type(frozenset.intersection(*[vote.feasible for vote in votes]))


def _authoritative(votes: list[Vote], mode: str) -> str:
    """Let the most trusted tier that carries the column decide it alone."""
    tier = min(vote.tier for vote in votes)
    return _combine([vote for vote in votes if vote.tier == tier], mode)


def _consensus(votes: list[Vote], mode: str) -> str:
    """Take the type the most files state, breaking ties by type priority."""
    counts = Counter(best_type(vote.feasible) for vote in votes)
    winning = max(counts.values())
    return best_type({type_name for type_name, count in counts.items() if count == winning})


def _union(votes: list[Vote], mode: str) -> str:
    """Take the simplest type that holds every value: the widening rule, always."""
    return _combine(votes, "loose")


#: The strategies share one signature; consensus and union have no use for the
#: inference mode beyond the feasible sets it already shaped.
_STRATEGIES = {"authoritative": _authoritative, "consensus": _consensus, "union": _union}
