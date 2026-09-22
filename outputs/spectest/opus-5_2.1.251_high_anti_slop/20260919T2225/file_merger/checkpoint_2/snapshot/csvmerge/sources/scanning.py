"""Collecting per-column type candidates from a stream of rows."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from ..types import ColumnType, candidate_types

#: What one file's scan reports: every column it holds, mapped to the types that
#: fit all of its values, or ``None`` when the column was never observed.
Candidates = dict[str, set[ColumnType] | None]


def accumulate(rows: Iterator[dict[str, Any]], ignore_nulls: bool, names: Iterable[str] = ()) -> Candidates:
    """Intersect the types accepted by every observed value, per column.

    ``names`` seeds columns that the file declares up front, so a header with no
    data rows behind it still contributes its columns to the output schema.
    """
    candidates: Candidates = dict.fromkeys(names)
    for row in rows:
        for name, value in row.items():
            if ignore_nulls and value is None:
                continue
            observed = candidates.get(name)
            matches = candidate_types(value)
            candidates[name] = matches if observed is None else observed & matches
    return candidates
