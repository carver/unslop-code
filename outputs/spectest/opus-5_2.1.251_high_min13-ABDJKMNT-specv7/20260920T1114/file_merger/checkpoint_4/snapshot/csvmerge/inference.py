"""Schema inference for runs that do not supply --schema.

The output columns are the union of every field name encountered, in ascending
lexicographic order. Each file is read once and summarised into the types that
accept all of its values for a column; `csvmerge.strategies` then reconciles those
summaries across files.

`--infer` decides what counts as evidence: under ``strict`` a missing value is an
observation that only ``string`` accepts, while ``loose`` skips it (ambiguities T2
and T28).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from csvmerge.schema import Column, Schema
from csvmerge.typespec import Primitive
from csvmerge.sources import Source
from csvmerge.strategies import PRECEDENCE, Evidence, resolve_type
from csvmerge.types import candidate_types
from csvmerge.values import typed_candidates

STRICT = "strict"
LOOSE = "loose"


@dataclass
class FileSummary:
    """What one file has to say about its columns.

    A column maps to the types that accept every value seen for it, or to ``None``
    while the file has shown no value at all — the column exists, but carries no
    type evidence.
    """

    rank: int
    columns: dict[str, set[str] | None] = field(default_factory=dict)

    def observe(self, name: str, candidates: set[str] | None) -> None:
        """Narrow what this file allows for `name` by one more observation."""
        seen = self.columns.get(name)
        if candidates is None or seen == {"string"}:
            self.columns.setdefault(name, seen)
            return
        self.columns[name] = candidates if seen is None else seen & candidates


def infer_schema(sources: list[Source], mode: str, strategy: str) -> Schema:
    """Resolve the output schema from the inputs alone."""
    summaries = [_summarise(source, mode) for source in sources]
    pooled = mode == LOOSE
    names = sorted({name for summary in summaries for name in summary.columns})
    return Schema(
        tuple(
            Column(
                name,
                Primitive(resolve_type(_evidence(name, summaries), strategy, pooled)),
            )
            for name in names
        )
    )


def _summarise(source: Source, mode: str) -> FileSummary:
    """Read one file and record the types its values leave open, column by column."""
    skip_nulls = mode == LOOSE
    summary = FileSummary(PRECEDENCE[source.format])
    with source.read() as (columns, records):
        for name in columns:
            summary.observe(name, None)
        for _, record in records:
            for name, value in record.items():
                skipped = value is None and skip_nulls
                summary.observe(name, None if skipped else _candidates(value, source.typed))
    return summary


def _candidates(value: object, typed: bool) -> set[str]:
    """The types one observed value is evidence for."""
    if value is None:
        return {"string"}
    if typed:
        return typed_candidates(value)
    return candidate_types(value)


def _evidence(name: str, summaries: list[FileSummary]) -> list[Evidence]:
    """What the files that actually saw values for `name` have to say about it."""
    return [
        Evidence(summary.rank, candidates)
        for summary in summaries
        if (candidates := summary.columns.get(name)) is not None
    ]
