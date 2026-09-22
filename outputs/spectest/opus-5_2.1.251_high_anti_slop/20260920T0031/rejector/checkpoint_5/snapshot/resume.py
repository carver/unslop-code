"""Picking up a run from the output file an interrupted one left behind."""

from __future__ import annotations

import json
import os

from config import REJECTION, TaskConfig
from rows import solution_count


def completed_rows(path: str, task: TaskConfig) -> int:
    """Leading rows of `path` that need not be produced again.

    Results are written in input order, so the number of complete leading rows is
    the number of input rows to skip. The count stops at the first row that is
    not complete, and every row from there on is generated again from scratch.
    """
    if not os.path.exists(path):
        return 0
    with open(path, encoding="utf-8") as handle:
        lines = [line for line in handle if line.strip()]
    return next((index for index, line in enumerate(lines) if not _complete(line, task)), len(lines))


def _complete(line: str, task: TaskConfig) -> bool:
    """Whether a written row already holds every solution its task asks for.

    Rejection and multi-solution rows can be written with fewer solutions than
    `num_solutions` when the run ended early, and an interrupted run can leave a
    half-written last line; both count as unfinished.
    """
    try:
        result = json.loads(line)
    except json.JSONDecodeError:
        return False
    if not (task.multi_solution or task.generation.scheme == REJECTION):
        return True
    return solution_count(result) >= task.num_solutions
