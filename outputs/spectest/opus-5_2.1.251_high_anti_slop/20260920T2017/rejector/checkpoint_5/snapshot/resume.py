"""Resuming a run from the rows an earlier run already wrote."""

from __future__ import annotations

import json
from itertools import takewhile
from pathlib import Path


def resume_point(path: str, num_solutions: int) -> int:
    """How many leading input rows an existing output file already covers.

    Rows are written in input order, so the finished rows at the front of the
    file are exactly the inputs a resumed run may skip. A row asking for several
    solutions counts as unfinished while it holds fewer than `num_solutions`, as
    does a partial line left by a run that was killed mid-write; everything from
    the first unfinished row on is dropped, leaving a file the run can append to.
    """
    file = Path(path)
    if not file.exists():
        return 0
    lines = file.read_text().splitlines()
    finished = list(takewhile(lambda line: _is_finished(line, num_solutions), lines))
    if len(finished) != len(lines):
        file.write_text("".join(line + "\n" for line in finished))
    return len(finished)


def _is_finished(line: str, num_solutions: int) -> bool:
    """Whether one written row is a complete result for its input."""
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return False
    output = record.get("output")
    return len(output) >= num_solutions if isinstance(output, list) else True
