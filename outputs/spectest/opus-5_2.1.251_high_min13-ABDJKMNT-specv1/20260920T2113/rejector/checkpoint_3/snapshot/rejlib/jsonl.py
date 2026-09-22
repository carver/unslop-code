"""Reading the JSONL input file and writing the JSONL output file."""

from __future__ import annotations

import json
from pathlib import Path

from rejlib.errors import ConfigError


def read_rows(path) -> list[dict]:
    """Parse the input file into rows; blank lines are skipped (T18)."""
    try:
        text = Path(path).read_text()
    except OSError as exc:
        raise ConfigError(f"cannot read input {path}: {exc}") from exc

    rows = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"input line {number} is not valid JSON: {exc}") from exc
        if not isinstance(row, dict):
            raise ConfigError(f"input line {number} is not a JSON object")
        rows.append(row)
    return rows


def write_rows(path, rows: list[dict]) -> None:
    """Write one JSON object per line, creating or overwriting ``path``."""
    with Path(path).open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def write_task_rows(directory, rows_by_task: dict[str, list[dict]]) -> None:
    """Write ``<directory>/<task_name>.jsonl`` for every task that ran."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for name, rows in rows_by_task.items():
        write_rows(directory / f"{name}.jsonl", rows)
