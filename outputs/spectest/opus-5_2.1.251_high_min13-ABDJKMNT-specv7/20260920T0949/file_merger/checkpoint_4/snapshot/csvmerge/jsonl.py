"""Reading JSON Lines inputs.

One JSON object per line. Values arrive decoded, so they travel as
:class:`~csvmerge.records.JsonValue` cells and are cast against the declared
type later; only a real ``null`` counts as a missing cell. A nested value is
refused outright when no ``--schema`` says what shape to expect.
"""

from __future__ import annotations

import json
from contextlib import contextmanager

from .errors import NestedValueError, SourceFormatError
from .records import JsonValue, Record, RecordStream

NESTED_WITHOUT_SCHEMA = "ERR 6 nested structure requires provided --schema"


@contextmanager
def open_jsonl(spec, nested_ok: bool):
    """Yield the records of one JSON Lines input."""
    with spec.open_text() as handle:
        yield RecordStream((), _records(spec, handle, nested_ok))


def _records(spec, handle, nested_ok: bool):
    for line_num, line in enumerate(handle, start=1):
        if not line.strip():  # blank and whitespace-only lines are ignored
            continue
        record = _parse_line(spec, line, line_num)
        yield Record(tuple(record), [_cell(value, nested_ok) for value in record.values()], line_num)


def _parse_line(spec, line: str, line_num: int) -> dict:
    try:
        record = json.loads(line)
    except json.JSONDecodeError as exc:
        raise SourceFormatError(f"{spec.path}:{line_num}: not valid JSON ({exc.msg})") from None
    if not isinstance(record, dict):
        raise NestedValueError(f"{spec.path}:{line_num}: line is not a flat JSON object")
    return record


def _cell(value, nested_ok: bool):
    """Hand one decoded JSON value on, unless nesting has nothing to match it."""
    if isinstance(value, (list, dict)) and not nested_ok:
        raise NestedValueError(NESTED_WITHOUT_SCHEMA)
    return None if value is None else JsonValue(value)
