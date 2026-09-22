"""Reading JSON Lines input: one flat UTF-8 JSON object per line.

Values arrive typed. Integers that do not fit a 64-bit integer become floats, as
the spec asks; nested values, and lines that are not objects at all, are rejected
(ambiguities T27 and T30).
"""

from __future__ import annotations

import json
from typing import Iterator, TextIO

from csvmerge.errors import EXIT_INPUT, EXIT_NESTED, MergeError

_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1


def read_jsonl(stream: TextIO, path: str) -> Iterator[dict[str, object]]:
    """Yield one record per non-blank line of a JSON Lines input."""
    for number, line in enumerate(stream, start=1):
        if line.strip():
            yield _record(line, f"{path}:{number}")


def _record(line: str, where: str) -> dict[str, object]:
    try:
        document = json.loads(line)
    except ValueError as error:
        raise MergeError(f"{where}: invalid JSON: {error}", EXIT_INPUT) from error
    if isinstance(document, list):
        raise MergeError(f"{where}: line is an array, not a flat object", EXIT_NESTED)
    if not isinstance(document, dict):
        raise MergeError(f"{where}: line is not a JSON object", EXIT_INPUT)
    return {name: _value(value, name, where) for name, value in document.items()}


def _value(value: object, name: str, where: str) -> object:
    """Check one value for flatness and give oversized integers a float spelling."""
    if isinstance(value, (dict, list)):
        raise MergeError(f"{where}: field {name!r} holds a nested value", EXIT_NESTED)
    if type(value) is int and not _INT64_MIN <= value <= _INT64_MAX:
        return float(value)
    return value
