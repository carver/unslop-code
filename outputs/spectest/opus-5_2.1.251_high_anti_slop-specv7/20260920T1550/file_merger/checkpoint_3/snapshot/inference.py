"""Collecting the types each column of one input is compatible with.

A column starts out as a candidate for every type and is narrowed by each
value it holds, so ``1`` and ``2.5`` in the same column leave ``float`` and
``string``.  Every value is text-compatible, so a column that reaches
``{"string"}`` cannot narrow further and needs no more inspection.
:mod:`schema` reconciles the per-input answers into the output schema.
"""

from __future__ import annotations

from typing import Iterable

from column_types import TYPE_PRIORITY, Record, value_candidates

# Type names still possible for each column of one input.  An empty set means
# the column was seen but never held a value, which types it as a string.
Candidates = dict[str, set[str]]

_STRING_ONLY = {"string"}


def observe(records: Iterable[Record], candidates: Candidates) -> Candidates:
    """Narrow ``candidates`` by every value in ``records`` and return it.

    Columns absent from ``candidates`` are added as they are encountered, which
    is how formats without a header, such as JSON Lines, get their column set.
    """
    for record in records:
        for name, value in record.items():
            if value is None:
                candidates.setdefault(name, set())
                continue
            seen = candidates.get(name)
            if seen == _STRING_ONLY:
                continue
            candidates[name] = value_candidates(value, TYPE_PRIORITY if not seen else seen)
    return candidates
