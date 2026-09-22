"""Reading JSONL input rows, rendering their prompts, and writing results."""

from __future__ import annotations

import json
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import TaskConfig
from errors import InputError

_FORMATTER = string.Formatter()


@dataclass(frozen=True)
class RenderedPrompt:
    """The system and user messages for a single input row."""

    system: str
    user: str


def load_rows(path: str) -> list[dict[str, Any]]:
    """Read a JSONL file into a list of objects, preserving file order."""
    try:
        lines = Path(path).read_text().splitlines()
    except OSError as exc:
        raise InputError(f"cannot read input {path}: {exc}") from exc

    rows = []
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        rows.append(_parse_row(line, index))
    return rows


def _parse_row(line: str, index: int) -> dict[str, Any]:
    try:
        row = json.loads(line)
    except json.JSONDecodeError as exc:
        raise InputError(f"row {index}: invalid JSON: {exc}") from exc
    if not isinstance(row, dict):
        raise InputError(f"row {index}: expected a JSON object")
    return row


def prepare_prompts(rows: list[dict[str, Any]], config: TaskConfig) -> list[RenderedPrompt]:
    """Render every row's prompts and check the fields the evaluation needs.

    Doing this up front means a row missing a field fails before any request is
    sent, rather than half way through a run.

    Raises:
        InputError: a row is missing a templated field or the answer field.
    """
    answer_field = config.evaluation.answer_field if config.evaluation else None
    prompts = []
    for index, row in enumerate(rows):
        prompt = RenderedPrompt(
            system=_render(config.prompt.system, row, index),
            user=_render(config.prompt.user, row, index),
        )
        if answer_field is not None and answer_field not in row:
            raise InputError(f"row {index}: missing field '{answer_field}' required by the evaluation")
        prompts.append(prompt)
    return prompts


def _render(template: str, row: dict[str, Any], index: int) -> str:
    for _, field, _, _ in _FORMATTER.parse(template):
        if field is not None and field not in row:
            raise InputError(f"row {index}: missing field '{field}' required by the prompt template")
    return template.format_map(row)


def write_results(path: str, records: list[dict[str, Any]]) -> None:
    """Write one JSON object per line, creating or overwriting the file."""
    with open(path, "w") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
