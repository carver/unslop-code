"""Resuming a run from the output file an interrupted run left behind."""

import json
from pathlib import Path
from typing import Any

from config import TaskConfig


def completed_rows(path: str, task: TaskConfig) -> int:
    """How many leading rows of ``path`` are finished work a resumed run can skip.

    Results are written in input order, so the count of complete leading rows is
    also the index of the first input row still to process. Counting stops at
    the first row that is not complete — a truncated line from an interrupted
    write, or a rejection or multi-solution row that collected fewer than
    ``num_solutions`` passing solutions — so that row is produced again.
    """
    if not Path(path).exists():
        return 0
    with open(path, encoding="utf-8") as handle:
        lines = handle.readlines()

    for index, line in enumerate(lines):
        if not _is_complete(line, task):
            return index
    return len(lines)


def _is_complete(line: str, task: TaskConfig) -> bool:
    result = _result(line)
    if result is None:
        return False
    if task.generation.scheme != "rejection" and task.num_solutions == 1:
        return True
    return _passing(result) >= task.num_solutions


def _result(line: str) -> dict[str, Any] | None:
    """One output row's ``result`` object, or ``None`` when the line is unusable."""
    try:
        row = json.loads(line)
    except json.JSONDecodeError:
        return None
    result = row.get("result") if isinstance(row, dict) else None
    return result if isinstance(result, dict) else None


def _passing(result: dict[str, Any]) -> int:
    """Passing solutions the row recorded: a count in the list format, a flag otherwise."""
    passed = result.get("passed")
    if isinstance(passed, bool):
        return 1 if passed else 0
    return passed if isinstance(passed, int) else 0
