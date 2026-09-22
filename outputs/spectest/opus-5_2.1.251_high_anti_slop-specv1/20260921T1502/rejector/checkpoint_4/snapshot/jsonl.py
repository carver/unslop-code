"""Reading and writing JSON Lines files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from errors import UsageError


def read_jsonl(path: Path) -> list[dict]:
    """Parse one JSON object per non-empty line."""
    try:
        text = path.read_text()
    except OSError as error:
        raise UsageError(f"cannot read input {path}: {error.strerror}") from None

    rows = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise UsageError(f"{path} line {number}: invalid JSON ({error.msg})") from None
        if not isinstance(row, dict):
            raise UsageError(f"{path} line {number}: expected a JSON object")
        rows.append(row)
    return rows


def write_jsonl(path: Path, records: Iterable[dict]) -> None:
    """Write one JSON object per line, replacing any existing file."""
    try:
        with path.open("w") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as error:
        raise UsageError(f"cannot write output {path}: {error.strerror}") from None
