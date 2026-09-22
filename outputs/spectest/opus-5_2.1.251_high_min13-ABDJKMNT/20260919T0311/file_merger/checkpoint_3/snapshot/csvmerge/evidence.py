"""What one file knows about one column's type, and how two files' views combine.

Text sources (CSV, TSV) are typed by probing their cell text; typed sources
(JSON Lines, Parquet) report the types they already carry.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import reduce
from typing import Any, Iterable

from .casting import TYPE_PRIORITY, has_time_part, matching_types, native_type, widen
from .cli import Options
from .formats import InputFile
from .records import CastPolicy
from .sources import open_source


@dataclass
class TextEvidence:
    """Which types have parsed every text value observed for one column."""

    candidates: set[str] = field(default_factory=lambda: set(TYPE_PRIORITY))
    saw_time_part: bool = False
    saw_value: bool = False

    def observe(self, value: Any) -> None:
        self.candidates &= matching_types(value)
        self.saw_time_part = self.saw_time_part or has_time_part(value)
        self.saw_value = True

    def pool(self, other: "TextEvidence") -> "TextEvidence":
        return TextEvidence(
            self.candidates & other.candidates,
            self.saw_time_part or other.saw_time_part,
            self.saw_value or other.saw_value,
        )

    def resolve(self) -> str:
        """The highest-priority type that parses every observed value."""
        if not self.saw_value:
            return "string"
        for name in TYPE_PRIORITY[:-1]:  # `string` is the guaranteed fallback
            # A date-only column stays `date` even though it also parses as a
            # timestamp, which would otherwise make `date` unreachable.
            if name in self.candidates and (name != "timestamp" or self.saw_time_part):
                return name
        return "string"


@dataclass
class TypedEvidence:
    """The types a typed source reported for one column."""

    types: set[str] = field(default_factory=set)

    def observe(self, value: Any) -> None:
        self.types.add(native_type(value))

    def pool(self, other: "TypedEvidence") -> "TypedEvidence":
        return TypedEvidence(self.types | other.types)

    def resolve(self) -> str:
        if not self.types:
            return "string"
        return reduce(widen, sorted(self.types, key=TYPE_PRIORITY.index))


def pool(left, right):
    """Two files' evidence for one column, merged into one.

    Text and typed evidence cannot be pooled value by value, so a mixed pair
    contributes only the types each side resolves to.
    """
    if type(left) is type(right):
        return left.pool(right)
    return TypedEvidence({widen(left.resolve(), right.resolve())})


def resolve_all(evidences: Iterable) -> set[str]:
    """The distinct types a group of files resolve this column to."""
    return {evidence.resolve() for evidence in evidences}


def file_evidence(source: InputFile, options: Options, policy: CastPolicy) -> dict:
    """One file's evidence per column, keyed by column name.

    A format that declares its own schema needs no scan at all; everything else
    is read once, observing the values the `--infer` mode counts as evidence.
    """
    with open_source(source, options) as opened:
        if opened.declared is not None:
            return {name: TypedEvidence({type_}) for name, type_ in opened.declared.items()}

        new_evidence = TypedEvidence if opened.typed else TextEvidence
        evidence = {name: new_evidence() for name in opened.columns}
        for row in opened.rows:
            for name, value in row.items():
                # Every encountered field name joins the column set, whether or
                # not its value says anything about the column's type.
                column = evidence.setdefault(name, new_evidence())
                if _is_evidence(value, opened.typed, options.infer, policy):
                    column.observe(value)
    return evidence


def _is_evidence(value: Any, typed: bool, mode: str, policy: CastPolicy) -> bool:
    """Whether a cell says anything about its column's type.

    A typed source's `null` never does. A text source's blank counts under
    `strict`, where it forces the column to `string`, but not under `loose`.
    """
    if typed:
        return value is not None
    return mode != "loose" or not policy.is_null(value)
