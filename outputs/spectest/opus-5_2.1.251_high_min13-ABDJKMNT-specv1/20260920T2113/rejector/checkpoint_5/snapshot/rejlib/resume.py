"""`--resume`: how much of a task's output file is already complete."""

from __future__ import annotations

from pathlib import Path

from rejlib.config import TaskConfig
from rejlib.jsonl import read_rows, write_rows
from rejlib.rows import solution_count


def completed_rows(path: Path, config: TaskConfig) -> int:
    """Leading output rows that may be skipped, dropping an incomplete tail.

    Outputs are written in input order, so the number of complete leading rows is
    the number of input rows to skip. A rejection or multi-solution row holding
    fewer passing solutions than `num_solutions` is not complete: it and every
    row after it are removed from the file and processed again (T82, T84).
    """
    if not path.is_file():
        return 0

    rows = read_rows(path)
    complete = next(
        (index for index, row in enumerate(rows) if _incomplete(config, row)), len(rows)
    )
    if complete < len(rows):
        write_rows(path, rows[:complete])
    return complete


def _incomplete(config: TaskConfig, row: dict) -> bool:
    """Whether a prior output row has to be produced again from scratch."""
    if config.generation.scheme != "rejection" and config.num_solutions == 1:
        return False
    return solution_count(row) < config.num_solutions
