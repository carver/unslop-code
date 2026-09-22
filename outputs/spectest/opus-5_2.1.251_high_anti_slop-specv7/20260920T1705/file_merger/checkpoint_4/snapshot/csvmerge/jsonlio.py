"""JSON Lines input: one UTF-8 JSON object per line.

Values arrive already typed, so no parsing rules apply here beyond JSON's own;
blank lines are skipped and anything that is not an object is rejected.  Nested
objects and arrays are handed on as they are: whether they are allowed is a
question for the schema, which the reader does not see.
"""

from __future__ import annotations

import json
from typing import Any, Iterator

from .errors import SourceFormatError
from .formats import InputRow, Source, open_text


def read_rows(source: Source) -> Iterator[InputRow]:
    """Yield each non-blank line as a mapping of field name to typed value."""
    with open_text(source.path, source.compression) as handle:
        for number, line in enumerate(handle, start=1):
            if line.strip():
                yield InputRow(number, _decode(source.path, number, line))


def _decode(path: str, number: int, line: str) -> dict[str, Any]:
    """Turn one line into a record, rejecting anything that is not an object."""
    try:
        record = json.loads(line)
    except ValueError as error:
        raise SourceFormatError(f"{path}:{number}: invalid JSON: {error}") from error
    if not isinstance(record, dict):
        raise SourceFormatError(
            f"{path}:{number}: expected a JSON object, got {type(record).__name__}"
        )
    return record
