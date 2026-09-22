"""JSON Lines input: one flat UTF-8 JSON object per line.

Values arrive already typed, so no parsing rules apply here beyond JSON's own;
blank lines are skipped and anything that is not a flat object is rejected.
"""

from __future__ import annotations

import json
from typing import Any, Iterator

from .errors import NestedDataError, SourceFormatError
from .formats import InputRow, Source, open_text


def read_rows(source: Source) -> Iterator[InputRow]:
    """Yield each non-blank line as a mapping of field name to typed value."""
    with open_text(source.path, source.compression) as handle:
        for number, line in enumerate(handle, start=1):
            if line.strip():
                yield InputRow(number, _decode(source.path, number, line))


def _decode(path: str, number: int, line: str) -> dict[str, Any]:
    """Turn one line into a flat record, rejecting anything else."""
    try:
        record = json.loads(line)
    except ValueError as error:
        raise SourceFormatError(f"{path}:{number}: invalid JSON: {error}") from error
    if not isinstance(record, dict):
        raise SourceFormatError(
            f"{path}:{number}: expected a JSON object, got {type(record).__name__}"
        )
    nested = sorted(name for name, value in record.items() if isinstance(value, (dict, list)))
    if nested:
        raise NestedDataError(
            f"{path}:{number}: field(s) {', '.join(nested)} hold nested values; "
            "only flat objects are supported"
        )
    return record
