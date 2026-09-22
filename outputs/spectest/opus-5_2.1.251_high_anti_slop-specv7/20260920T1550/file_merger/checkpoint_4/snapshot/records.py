"""One input row: the cells it holds and the input it came from.

Every reader hands the pipeline :class:`SourceRecord` objects, so a value that
turns out not to fit its column can be reported against the file and the line
it was read from.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

# A cell as it arrives from an input: raw text from CSV and TSV, already typed
# from JSON Lines and Parquet, ``None`` when the source says the value is null.
# Objects and arrays only reach a column the schema declares nested.
FieldValue = str | int | float | bool | Decimal | date | datetime | bytes | dict | list | None

# One input row, keyed by column name.  A value of ``None`` means the source
# had nothing for that column: a null, an empty cell or a missing field.
Record = dict[str, FieldValue]


@dataclass(frozen=True)
class Origin:
    """Where a record was read and how the input it came from types its cells.

    CSV and TSV hand over raw text, so a nested cell arrives as JSON text that
    has to be parsed first; JSON Lines and Parquet hand over values that are
    already typed.  ``line`` is the line the record ends on, or its row number
    in a Parquet file.
    """

    file: str
    line: int
    text_cells: bool


@dataclass(frozen=True)
class SourceRecord:
    """One row of one input, with the origin its errors are reported against."""

    values: Record
    origin: Origin
