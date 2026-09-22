"""JSONL input/output and prompt rendering for the rows of a task."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from config import TaskConfig
from errors import RejectorError
from templates import Message, placeholders, render

Row = dict[str, Any]


def load_rows(path: str) -> list[Row]:
    """Read a JSONL file into a list of row objects, preserving file order."""
    rows: list[Row] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(_parse_row(line, index=len(rows)))
    return rows


def _parse_row(line: str, index: int) -> Row:
    try:
        row = json.loads(line)
    except json.JSONDecodeError as exc:
        raise RejectorError(f"input row {index}: invalid JSON ({exc.msg})") from None
    if not isinstance(row, dict):
        raise RejectorError(f"input row {index}: expected a JSON object")
    return row


def prepare_messages(rows: Iterable[Row], task: TaskConfig) -> list[list[Message]]:
    """Render the chat messages for every row, failing on rows missing a required field."""
    required = required_fields(task)
    rendered = []
    for index, row in enumerate(rows):
        missing = sorted(required - row.keys())
        if missing:
            fields = ", ".join(f"'{name}'" for name in missing)
            raise RejectorError(f"input row {index}: missing field {fields}")
        rendered.append(render(task.prompt, row))
    return rendered


def required_fields(task: TaskConfig) -> set[str]:
    """Row fields the task needs: its prompt, plus whatever its evaluation reads."""
    fields = placeholders(task.prompt.system, task.prompt.user)
    evaluation = task.evaluation
    if evaluation is None:
        return fields

    if evaluation.answer_field:
        fields.add(evaluation.answer_field)
    if evaluation.judge_prompt:
        fields |= placeholders(evaluation.judge_prompt.system, evaluation.judge_prompt.user)
    if evaluation.command_template:
        fields |= placeholders(evaluation.command_template)
    return fields


def write_results(path: str, results: Iterable[dict[str, Any]]) -> None:
    """Write one JSON object per line, overwriting any existing file."""
    with open(path, "w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result) + "\n")
