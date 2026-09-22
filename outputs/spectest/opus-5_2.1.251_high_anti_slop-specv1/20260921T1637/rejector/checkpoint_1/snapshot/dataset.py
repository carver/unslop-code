"""Input loading and prompt rendering, both validated before any request is sent."""

import json
from typing import Any

from config import PromptConfig, TaskConfig
from errors import InputError

Row = dict[str, Any]
Messages = list[dict[str, str]]


def load_rows(path: str) -> list[Row]:
    """Read a JSONL file into a list of rows, preserving file order."""
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError as exc:
        raise InputError(f"cannot read input file {path}: {exc}") from exc

    rows = []
    for number, line in enumerate(lines, start=1):
        if line.strip():
            rows.append(_parse_row(path, number, line))
    return rows


def build_prompts(rows: list[Row], task: TaskConfig) -> list[Messages]:
    """Render the chat messages for every row and check the fields the evaluation needs."""
    answer_field = task.evaluation.answer_field if task.evaluation else None
    prompts = []
    for index, row in enumerate(rows):
        if answer_field is not None and answer_field not in row:
            raise InputError(f"row {index} is missing field '{answer_field}' required by the evaluation")
        prompts.append(_render_messages(task.prompt, row, index))
    return prompts


def _parse_row(path: str, number: int, line: str) -> Row:
    try:
        row = json.loads(line)
    except json.JSONDecodeError as exc:
        raise InputError(f"{path}: line {number} is not valid JSON: {exc.msg}") from exc
    if not isinstance(row, dict):
        raise InputError(f"{path}: line {number} is not a JSON object")
    return row


def _render_messages(prompt: PromptConfig, row: Row, index: int) -> Messages:
    messages = []
    if prompt.system:
        messages.append({"role": "system", "content": _render(prompt.system, row, index)})
    messages.append({"role": "user", "content": _render(prompt.user, row, index)})
    return messages


def _render(template: str, row: Row, index: int) -> str:
    try:
        return template.format_map(row)
    except KeyError as exc:
        field = exc.args[0]
        raise InputError(f"row {index} is missing field '{field}' referenced by the prompt template") from exc
