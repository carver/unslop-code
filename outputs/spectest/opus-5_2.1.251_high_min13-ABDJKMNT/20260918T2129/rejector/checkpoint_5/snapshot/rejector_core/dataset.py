"""JSONL input loading."""

from __future__ import annotations

import json
from pathlib import Path

from .errors import InputError


def load_rows(path: str | Path) -> list[dict]:
    """Read a JSONL file into a list of row objects, skipping blank lines."""
    path = Path(path)
    if not path.is_file():
        raise InputError(f"input file not found: {path}")

    rows = []
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise InputError(f"input line {line_number} is not valid JSON: {exc.msg}") from exc
        if not isinstance(row, dict):
            raise InputError(f"input line {line_number} is not a JSON object")
        rows.append(row)
    return rows
