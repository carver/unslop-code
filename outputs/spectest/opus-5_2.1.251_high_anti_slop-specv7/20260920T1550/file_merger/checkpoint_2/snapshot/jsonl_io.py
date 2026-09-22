"""Reading JSON Lines (NDJSON) inputs.

One UTF-8 JSON object per line, flat: a value may be a string, a number, a
boolean or ``null``, never an array or another object.  Blank and whitespace
lines are skipped, and keys are taken as they are written, so ``id`` and ``ID``
are different columns.  Numbers arrive typed, so an integral one that fits in
64 bits stays an integer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from column_types import Record, narrow_number
from errors import DataError, SchemaError
from inference import Candidates, observe
from streams import open_text


class JsonlReader:
    """A JSON Lines input, streamed one line at a time."""

    format = "jsonl"

    def __init__(self, path: Path, compression: str) -> None:
        self._path = path
        self._compression = compression

    def records(self) -> Iterator[Record]:
        """Stream the objects of the input as records."""
        with open_text(self._path, self._compression) as handle:
            for number, line in enumerate(handle, start=1):
                if line.strip():
                    yield self._record(line, number)

    def scan(self) -> Candidates:
        """Type every column from the values of the objects that carry it."""
        return observe(self.records(), {})

    def _record(self, line: str, number: int) -> Record:
        document = self._parse(line, number)
        nested = sorted(key for key, value in document.items() if isinstance(value, (dict, list)))
        if nested:
            raise SchemaError(
                f"{self._path}: line {number}: field(s) {', '.join(nested)} are not flat; "
                "JSON Lines objects may not hold arrays or objects"
            )
        return {key: narrow_number(value) for key, value in document.items()}

    def _parse(self, line: str, number: int) -> dict[str, object]:
        try:
            document = json.loads(line)
        except json.JSONDecodeError as error:
            raise DataError(f"{self._path}: line {number}: invalid JSON ({error.msg})") from error
        if not isinstance(document, dict):
            raise DataError(f"{self._path}: line {number}: expected a JSON object")
        return document
