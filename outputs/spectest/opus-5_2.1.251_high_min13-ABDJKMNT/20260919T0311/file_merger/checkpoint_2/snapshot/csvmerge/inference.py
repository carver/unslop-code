"""Inferring the output schema from heterogeneous inputs.

Each file contributes its own view of every column it contains; a
`--schema-strategy` then reconciles the views that disagree.
"""
from __future__ import annotations

from collections import Counter
from functools import reduce
from typing import Sequence

from .casting import TYPE_PRIORITY, widen
from .cli import Options
from .evidence import file_evidence, pool, resolve_all
from .formats import InputFile
from .records import CastPolicy
from .schema import Column, Schema

#: How much type information each format carries. `authoritative` trusts the
#: highest rank that has the column: Parquet declares its schema, JSON Lines
#: carries a type per value, and CSV or TSV carry none at all.
SOURCE_RANK = {"csv": 0, "tsv": 0, "jsonl": 1, "parquet": 2}


def _authoritative(entries: list[tuple[int, object]], mode: str) -> str:
    """The most type-aware files decide; among themselves, `--infer` settles it."""
    best = max(rank for rank, _ in entries)
    evidences = [evidence for rank, evidence in entries if rank == best]
    if mode == "loose":
        return reduce(pool, evidences).resolve()
    types = resolve_all(evidences)
    return types.pop() if len(types) == 1 else "string"


def _consensus(entries: list[tuple[int, object]], mode: str) -> str:
    """The type the most files resolve to, with ties going to the higher priority."""
    votes = Counter(evidence.resolve() for _, evidence in entries)
    winning = max(votes.values())
    return min((name for name, count in votes.items() if count == winning),
               key=TYPE_PRIORITY.index)


def _union(entries: list[tuple[int, object]], mode: str) -> str:
    """The simplest type that can hold what every file observed."""
    types = sorted(resolve_all(evidence for _, evidence in entries), key=TYPE_PRIORITY.index)
    return reduce(widen, types)


STRATEGIES = {
    "authoritative": _authoritative,
    "consensus": _consensus,
    "union": _union,
}


def infer_schema(inputs: Sequence[InputFile], options: Options, policy: CastPolicy) -> Schema:
    """Resolve the output schema from the union of every input's columns."""
    per_file = [(SOURCE_RANK[source.format], file_evidence(source, options, policy))
                for source in inputs]
    names = sorted({name for _, evidence in per_file for name in evidence})
    strategy = STRATEGIES[options.schema_strategy]

    return Schema(tuple(
        Column(name, strategy(
            [(rank, evidence[name]) for rank, evidence in per_file if name in evidence],
            options.infer,
        ))
        for name in names
    ))
