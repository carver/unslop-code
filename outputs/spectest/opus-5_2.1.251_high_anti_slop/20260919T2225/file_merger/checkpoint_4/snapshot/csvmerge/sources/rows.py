"""The shape every reader hands back: one row, and where in its file it came from."""

from __future__ import annotations

from typing import Any, NamedTuple


class SourceRow(NamedTuple):
    """One input row: its values by field name, plus the place it was read from.

    ``line`` is the 1-based line number in the text formats and the row's
    ordinal in Parquet; it appears in the messages a rejected cast raises.
    """

    values: dict[str, Any]
    line: int
