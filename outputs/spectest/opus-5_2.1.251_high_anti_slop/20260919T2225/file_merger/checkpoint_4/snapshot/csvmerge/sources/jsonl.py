"""Reading JSON Lines: one UTF-8 JSON object per line."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from ..errors import MalformedInputError, NestedDataError
from .files import InputSpec, ReadOptions, open_text
from .rows import SourceRow
from .scanning import Candidates, accumulate


def read_rows(spec: InputSpec, _options: ReadOptions, allow_nested: bool) -> Iterator[SourceRow]:
    """Yield one row per object; blank and whitespace-only lines are ignored.

    Nested objects and arrays are handed over untouched when a ``--schema``
    declares what to do with them, and rejected when there is nothing to cast
    them to.
    """
    with open_text(spec) as stream:
        for number, line in enumerate(stream, start=1):
            if line.strip():
                yield SourceRow(_parse_object(line, spec.path, number, allow_nested), number)


def scan_types(spec: InputSpec, options: ReadOptions, ignore_nulls: bool) -> Candidates:
    """Report the types each field of this file could take, over the union of its keys."""
    return accumulate(read_rows(spec, options, False), ignore_nulls)


def _parse_object(line: str, path: str, number: int, allow_nested: bool) -> dict[str, Any]:
    try:
        record = json.loads(line)
    except json.JSONDecodeError as error:
        raise MalformedInputError(f"{path}:{number}: invalid JSON ({error.msg})") from error
    if not isinstance(record, dict):
        raise NestedDataError(f"{path}:{number}: expected a JSON object, found {type(record).__name__}")
    if not allow_nested:
        _reject_nested(record, path, number)
    return record


def _reject_nested(record: dict[str, Any], path: str, number: int) -> None:
    nested = sorted(name for name, value in record.items() if isinstance(value, (dict, list)))
    if nested:
        raise NestedDataError(
            f"nested structure requires provided --schema"
            f" in field(s) {', '.join(nested)} (file={path} line={number})"
        )
