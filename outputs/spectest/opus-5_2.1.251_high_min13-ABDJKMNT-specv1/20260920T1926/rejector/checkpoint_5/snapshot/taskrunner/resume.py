"""`--resume`: how much of an existing output file counts as already done.

Outputs are written in input order, so the leading complete rows of an
existing file are exactly the leading input rows that can be skipped. A row
that stopped short of the solutions its task asks for is not complete and is
run again from scratch.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .config import REJECTION, TaskConfig


def resume_point(path: str | Path, config: TaskConfig) -> int:
    """How many leading input rows an earlier run already finished."""
    target = Path(path)
    if not target.exists():
        return 0
    records = [json.loads(line) for line in target.read_text().splitlines() if line.strip()]
    done = 0
    while done < len(records) and _complete(records[done], config):
        done += 1
    if done < len(records):
        _trim(target, done)
    return done


def _complete(record: Mapping[str, Any], config: TaskConfig) -> bool:
    """Whether a written row holds every solution its task was asked for."""
    output = record.get("output")
    if isinstance(output, list):
        return len(output) >= config.num_solutions
    if config.generation.scheme == REJECTION:
        return output is not None
    return True


def _trim(path: Path, keep: int) -> None:
    """Drop the incomplete rows so new results append straight after the good ones."""
    lines = path.read_text().splitlines()
    path.write_text("".join(line + "\n" for line in lines[:keep]))
