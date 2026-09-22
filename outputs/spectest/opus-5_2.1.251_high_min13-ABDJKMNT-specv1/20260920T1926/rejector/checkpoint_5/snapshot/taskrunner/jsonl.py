"""Reading the JSONL input file and writing the JSONL output file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .errors import ConfigError


def read_rows(path: str | Path) -> list[dict[str, Any]]:
    """Parse the input file; every non-blank line must be a JSON object."""
    try:
        text = Path(path).read_text()
    except OSError as error:
        raise ConfigError(f"cannot read input {path}: {error}") from error

    rows = []
    for index, line in enumerate(text.splitlines()):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ConfigError(f"row {index}: invalid JSON ({error})") from None
        if not isinstance(row, dict):
            raise ConfigError(f"row {index}: expected a JSON object")
        rows.append(row)
    return rows


def write_records(
    path: str | Path, records: Iterable[Mapping[str, Any]], append: bool = False
) -> None:
    """Write one JSON object per line, overwriting unless `append` is set."""
    with Path(path).open("a" if append else "w") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
