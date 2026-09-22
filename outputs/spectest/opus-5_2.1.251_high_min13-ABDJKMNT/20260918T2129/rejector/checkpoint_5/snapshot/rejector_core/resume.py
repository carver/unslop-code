"""Resuming a run from the output file a previous run left behind."""

from __future__ import annotations

import json
from pathlib import Path

from .config import TaskConfig


def rows_already_done(path: Path, task: TaskConfig) -> int:
    """How many leading input rows the existing output already covers.

    Outputs are written in input order, so the count of leading complete
    rows is the number of input rows to skip.  A row an interrupted run left
    incomplete is dropped from the file, together with everything after it,
    so that it can be produced again from scratch.
    """
    if not path.is_file():
        return 0

    lines = [line for line in path.read_text().splitlines() if line.strip()]
    done = _leading_complete(lines, task)
    if done < len(lines):
        path.write_text("".join(f"{line}\n" for line in lines[:done]))
    return done


def _leading_complete(lines: list[str], task: TaskConfig) -> int:
    for index, line in enumerate(lines):
        if _incomplete(json.loads(line), task):
            return index
    return len(lines)


def _incomplete(document: dict, task: TaskConfig) -> bool:
    """Whether a written row still has solutions left to collect.

    Only schemes that can retry are reconsidered: a greedy or sample row is
    finished whatever it produced, while a multi-solution or rejection row
    holding fewer solutions than asked for was cut short.
    """
    if not task.list_format and task.generation.scheme != "rejection":
        return False
    return _solutions_in(document) < task.num_solutions


def _solutions_in(document: dict) -> int:
    output = document.get("output")
    if isinstance(output, list):
        return len(output)
    return 0 if output is None else 1
