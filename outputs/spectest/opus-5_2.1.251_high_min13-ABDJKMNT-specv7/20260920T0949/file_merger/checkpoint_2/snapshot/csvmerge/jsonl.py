"""Reading JSON Lines inputs.

One flat JSON object per line. Values arrive typed, so they are rendered to
text here; only a real ``null`` counts as a missing cell.
"""

from __future__ import annotations

import json
from contextlib import contextmanager

from .errors import NestedValueError, SourceFormatError
from .records import Record, RecordStream, text_of

#: Range of a signed 64 bit integer, the "within range" of the number rule.
_INT_MIN, _INT_MAX = -(2**63), 2**63 - 1


@contextmanager
def open_jsonl(spec):
    """Yield the records of one JSON Lines input."""
    with spec.open_text() as handle:
        yield RecordStream((), _records(spec, handle))


def _records(spec, handle):
    for line_num, line in enumerate(handle, start=1):
        if not line.strip():  # blank and whitespace-only lines are ignored
            continue
        record = _parse_line(spec, line, line_num)
        yield Record(tuple(record), [_value_text(spec, line_num, value) for value in record.values()], line_num)


def _parse_line(spec, line: str, line_num: int) -> dict:
    try:
        record = json.loads(line)
    except json.JSONDecodeError as exc:
        raise SourceFormatError(f"{spec.path}:{line_num}: not valid JSON ({exc.msg})") from None
    if not isinstance(record, dict):
        raise NestedValueError(f"{spec.path}:{line_num}: line is not a flat JSON object")
    return record


def _value_text(spec, line_num: int, value) -> str | None:
    """Render one JSON value, applying the number rule and rejecting nesting."""
    if isinstance(value, (list, dict)):
        raise NestedValueError(f"{spec.path}:{line_num}: nested value in a JSON object")
    if isinstance(value, float) and value.is_integer() and _INT_MIN <= value <= _INT_MAX:
        return str(int(value))
    return text_of(value)
