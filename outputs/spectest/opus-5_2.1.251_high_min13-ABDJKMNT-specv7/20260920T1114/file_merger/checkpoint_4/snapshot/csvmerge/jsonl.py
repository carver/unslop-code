"""Reading JSON Lines input: one UTF-8 JSON object per line.

Values arrive typed. Integers that do not fit a 64-bit integer become floats, as
the spec asks. Nested objects and arrays are accepted only when a `--schema`
describes them; without one they are error 6 (ambiguities T27 and T30).
"""

from __future__ import annotations

import json
from typing import Iterator, TextIO

from csvmerge.errors import EXIT_INPUT, MergeError, nested_needs_schema

_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1

Records = Iterator[tuple[int, dict[str, object]]]


def read_jsonl(stream: TextIO, path: str, nested: bool) -> Records:
    """Yield the line number and record of each non-blank JSON Lines row."""
    for number, line in enumerate(stream, start=1):
        if line.strip():
            yield number, _record(line, f"{path}:{number}", nested)


def _record(line: str, where: str, nested: bool) -> dict[str, object]:
    try:
        document = json.loads(line)
    except ValueError as error:
        raise MergeError(f"{where}: invalid JSON: {error}", EXIT_INPUT) from error
    if isinstance(document, list) and not nested:
        raise nested_needs_schema()
    if not isinstance(document, dict):
        raise MergeError(f"{where}: line is not a JSON object", EXIT_INPUT)
    return {name: _value(value, nested) for name, value in document.items()}


def _value(value: object, nested: bool) -> object:
    """Widen oversized integers, and hold nested values to the schema rule."""
    if isinstance(value, dict):
        _require_schema(nested)
        return {name: _value(item, nested) for name, item in value.items()}
    if isinstance(value, list):
        _require_schema(nested)
        return [_value(item, nested) for item in value]
    if type(value) is int and not _INT64_MIN <= value <= _INT64_MAX:
        return float(value)
    return value


def _require_schema(nested: bool) -> None:
    if not nested:
        raise nested_needs_schema()
