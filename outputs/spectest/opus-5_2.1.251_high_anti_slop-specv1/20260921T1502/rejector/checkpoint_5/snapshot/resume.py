"""Picking up a run from the rows an earlier one already wrote."""

from __future__ import annotations

from itertools import takewhile
from pathlib import Path

from config import TaskConfig
from jsonl import read_jsonl, write_jsonl


def resume_from(path: Path, config: TaskConfig) -> int:
    """How many leading input rows an existing output file already covers.

    Rows are written in input order, so the complete rows at the front of the
    file are exactly what a resumed run may skip. A row that kept fewer
    solutions than the task asks for is not complete: the file is cut back to
    the rows before it, which the run then produces again from scratch.
    """
    if not path.exists():
        return 0

    records = read_jsonl(path)
    complete = list(takewhile(lambda record: _complete(config, record), records))
    if len(complete) < len(records):
        write_jsonl(path, complete)
    return len(complete)


def _complete(config: TaskConfig, record: dict) -> bool:
    """Whether a written row already carries everything its task asks for.

    Only rejection sampling and multiple solution tasks can come up short; any
    other scheme writes whatever the single pass over the row produced.
    """
    if config.generation.scheme != "rejection" and config.num_solutions == 1:
        return True
    output = record["output"]
    kept = len(output) if isinstance(output, list) else int(output is not None)
    return kept >= config.num_solutions
