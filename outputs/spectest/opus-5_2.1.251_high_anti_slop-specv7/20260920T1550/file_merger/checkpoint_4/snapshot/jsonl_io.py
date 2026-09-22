"""Reading JSON Lines (NDJSON) inputs.

One UTF-8 JSON object per line.  A value may be a string, a number, a boolean
or ``null``; it may also be an array or an object, but only when ``--schema``
says what that column should become, since inference is flat.  Blank and
whitespace lines are skipped, and keys are taken as they are written, so ``id`` and ``ID``
are different columns.  Numbers arrive typed, so an integral one that fits in
64 bits stays an integer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from column_types import narrow_number
from errors import DataError, SchemaError
from inference import Candidates, observe
from records import Origin, Record, SourceRecord
from streams import open_text


class JsonlReader:
    """A JSON Lines input, streamed one line at a time."""

    format = "jsonl"

    def __init__(self, path: Path, compression: str, allow_nested: bool) -> None:
        self._path = path
        self._compression = compression
        self._allow_nested = allow_nested

    def records(self) -> Iterator[SourceRecord]:
        """Stream the objects of the input as records."""
        with open_text(self._path, self._compression) as handle:
            for number, line in enumerate(handle, start=1):
                if line.strip():
                    origin = Origin(str(self._path), number, False)
                    yield SourceRecord(self._record(line, number), origin)

    def scan(self) -> Candidates:
        """Type every column from the values of the objects that carry it."""
        return observe(self.records(), {})

    def _record(self, line: str, number: int) -> Record:
        document = self._parse(line, number)
        if not self._allow_nested:
            self._reject_nested(document, number)
        return {key: narrow_number(value) for key, value in document.items()}

    def _reject_nested(self, document: dict[str, object], number: int) -> None:
        """Without a schema nothing says what an array or an object should become."""
        nested = sorted(key for key, value in document.items() if isinstance(value, (dict, list)))
        if nested:
            raise SchemaError(
                f"{self._path}: line {number}: nested structure requires provided --schema; "
                f"field(s) {', '.join(nested)} hold an array or an object"
            )

    def _parse(self, line: str, number: int) -> dict[str, object]:
        try:
            document = json.loads(line)
        except json.JSONDecodeError as error:
            raise DataError(f"{self._path}: line {number}: invalid JSON ({error.msg})") from error
        if not isinstance(document, dict):
            raise DataError(f"{self._path}: line {number}: expected a JSON object")
        return document
