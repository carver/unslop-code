"""`--resume`: how much of an existing output file an earlier run finished."""

from __future__ import annotations

import json
from itertools import takewhile
from pathlib import Path

from .config import TaskConfig

REJECTION = "rejection"


def resume_point(path: Path, task: TaskConfig) -> int:
    """How many leading input rows the output file already covers.

    Rows are written in input order, so the file has to stay a prefix of the
    results: the scan stops at the first row that is not a finished result and
    truncates the file there, leaving the rest to be generated again.
    """
    if not path.exists():
        return 0

    lines = [line for line in path.read_text().splitlines() if line.strip()]
    kept = list(takewhile(lambda line: _complete(line, task), lines))
    if len(kept) < len(lines):
        path.write_text("".join(line + "\n" for line in kept))
    return len(kept)


def _complete(line: str, task: TaskConfig) -> bool:
    """Whether one written row holds every solution the task asked for.

    Only the schemes that can stop early -- rejection, and any task collecting
    several solutions -- can leave a row unfinished; every other row is as
    complete as it will ever be.
    """
    try:
        output = json.loads(line).get("output")
    except json.JSONDecodeError:
        return False
    if task.list_format:
        return len(output or []) >= task.num_solutions
    if task.generation.scheme == REJECTION:
        return output is not None
    return True
