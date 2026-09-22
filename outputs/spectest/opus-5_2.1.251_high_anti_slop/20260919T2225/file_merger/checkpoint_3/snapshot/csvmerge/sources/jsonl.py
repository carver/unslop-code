"""Reading JSON Lines: one flat UTF-8 JSON object per line."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from ..errors import MalformedInputError, NestedDataError
from .files import InputSpec, ReadOptions, open_text
from .scanning import Candidates, accumulate


def read_rows(spec: InputSpec, _options: ReadOptions) -> Iterator[dict[str, Any]]:
    """Yield one dictionary per object; blank and whitespace-only lines are ignored."""
    with open_text(spec) as stream:
        for number, line in enumerate(stream, start=1):
            if line.strip():
                yield _parse_object(line, spec.path, number)


def scan_types(spec: InputSpec, options: ReadOptions, ignore_nulls: bool) -> Candidates:
    """Report the types each field of this file could take, over the union of its keys."""
    return accumulate(read_rows(spec, options), ignore_nulls)


def _parse_object(line: str, path: str, number: int) -> dict[str, Any]:
    try:
        record = json.loads(line)
    except json.JSONDecodeError as error:
        raise MalformedInputError(f"{path}:{number}: invalid JSON ({error.msg})") from error
    if not isinstance(record, dict):
        raise NestedDataError(f"{path}:{number}: expected a JSON object, found {type(record).__name__}")
    nested = [name for name, value in record.items() if isinstance(value, (dict, list))]
    if nested:
        raise NestedDataError(f"{path}:{number}: nested value in field(s) {', '.join(sorted(nested))}")
    return record
