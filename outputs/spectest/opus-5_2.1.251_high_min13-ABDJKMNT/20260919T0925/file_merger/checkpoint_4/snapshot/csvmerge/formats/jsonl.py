"""JSON Lines sources: one flat JSON object per line."""

from __future__ import annotations

import json

from ..errors import InputError, NestedDataError
from ..origin import Origin
from ..values import normalize_number
from .detect import open_text


class JsonlSource:
    """An NDJSON input.

    Values arrive typed, so this source outranks delimited text when schemas
    disagree; Parquet, which carries a declared schema, outranks it in turn
    (AMBIGUITIES T19).
    """

    tier = 2

    def __init__(self, path, compression, allow_nested):
        self.path = path
        self._compression = compression
        self._allow_nested = allow_nested

    def fields(self):
        """JSONL declares no columns; names are discovered while reading."""
        return ()

    def records(self):
        """Yield ``(origin, {key: value})`` for each non-blank line."""
        with open_text(self.path, self._compression, newline="\n") as stream:
            for number, line in enumerate(stream, start=1):
                if line.strip():
                    origin = Origin(self.path, number)
                    yield origin, self._decode(line, origin)

    def _decode(self, line, origin):
        try:
            document = json.loads(line)
        except ValueError as error:
            raise InputError(f"{origin}: not valid JSON: {error}") from error
        if not isinstance(document, dict):
            raise InputError(f"{origin}: expected a JSON object, not {type(document).__name__}")
        return {name: self._value(name, value, origin) for name, value in document.items()}

    def _value(self, name, value, origin):
        """Return `value` normalized, rejecting nesting when no schema declares it."""
        if isinstance(value, (list, dict)):
            if not self._allow_nested:
                raise NestedDataError(
                    f"nested structure requires provided --schema (field={name!r} {origin})"
                )
            return value
        return normalize_number(value)
