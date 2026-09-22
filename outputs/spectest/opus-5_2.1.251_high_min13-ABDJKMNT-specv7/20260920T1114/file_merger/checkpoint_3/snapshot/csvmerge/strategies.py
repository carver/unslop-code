"""Reconciling per-file type evidence into one type per output column.

Each file contributes the set of types that accept every value it showed for a
column; the strategies differ in how much weight a file's evidence carries.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from csvmerge.detect import CSV, JSONL, PARQUET, TSV
from csvmerge.types import highest_priority

AUTHORITATIVE = "authoritative"
CONSENSUS = "consensus"
UNION = "union"

# Typed sources come first; JSONL ranks with the text formats (ambiguity T23).
PRECEDENCE = {PARQUET: 0, CSV: 1, TSV: 1, JSONL: 1}


@dataclass(frozen=True)
class Evidence:
    """One file's say about one column: its precedence and the types that fit."""

    rank: int
    candidates: set[str]


def resolve_type(evidence: list[Evidence], strategy: str, pooled: bool) -> str:
    """The output type of a column, given what every file that saw it reported.

    `pooled` carries `--infer loose`: the peers of the authoritative tier then pool
    their values instead of comparing the type each file would infer alone. The
    other two strategies define their own reconciliation and ignore it.
    """
    if not evidence:
        return "string"
    return _STRATEGIES[strategy](evidence, pooled)


def _authoritative(evidence: list[Evidence], pooled: bool) -> str:
    """Only the most trusted sources that saw the column have a say."""
    best = min(item.rank for item in evidence)
    return _reconcile([item for item in evidence if item.rank == best], pooled)


def _consensus(evidence: list[Evidence], pooled: bool) -> str:
    """Each file votes with the type it would infer alone; the most votes wins."""
    votes = Counter(highest_priority(item.candidates) for item in evidence)
    winning = max(votes.values())
    return highest_priority(
        {name for name, count in votes.items() if count == winning}
    )


def _union(evidence: list[Evidence], pooled: bool) -> str:
    """The most specific type that accepts every value observed anywhere."""
    return highest_priority(_common(evidence))


def _reconcile(evidence: list[Evidence], pooled: bool) -> str:
    """Combine peers the way `--infer` asks: per file under strict, pooled under loose."""
    if pooled:
        return highest_priority(_common(evidence))
    types = {highest_priority(item.candidates) for item in evidence}
    return types.pop() if len(types) == 1 else "string"


def _common(evidence: list[Evidence]) -> set[str]:
    return set.intersection(*(item.candidates for item in evidence))


_STRATEGIES = {
    AUTHORITATIVE: _authoritative,
    CONSENSUS: _consensus,
    UNION: _union,
}
