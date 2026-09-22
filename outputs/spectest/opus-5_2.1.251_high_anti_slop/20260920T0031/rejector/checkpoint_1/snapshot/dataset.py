"""JSONL input/output and prompt rendering for the rows of a task."""

from __future__ import annotations

import json
from collections.abc import Iterable
from string import Formatter
from typing import Any

from config import PromptConfig, TaskConfig
from errors import RejectorError

Message = dict[str, str]


def load_rows(path: str) -> list[dict[str, Any]]:
    """Read a JSONL file into a list of row objects, preserving file order."""
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(_parse_row(line, index=len(rows)))
    return rows


def _parse_row(line: str, index: int) -> dict[str, Any]:
    try:
        row = json.loads(line)
    except json.JSONDecodeError as exc:
        raise RejectorError(f"input row {index}: invalid JSON ({exc.msg})") from None
    if not isinstance(row, dict):
        raise RejectorError(f"input row {index}: expected a JSON object")
    return row


def prepare_messages(rows: Iterable[dict[str, Any]], task: TaskConfig) -> list[list[Message]]:
    """Render the chat messages for every row, failing on rows missing a required field."""
    required = _placeholders(task.prompt.system) | _placeholders(task.prompt.user)
    if task.evaluation and task.evaluation.answer_field:
        required.add(task.evaluation.answer_field)

    rendered = []
    for index, row in enumerate(rows):
        missing = sorted(required - row.keys())
        if missing:
            fields = ", ".join(f"'{name}'" for name in missing)
            raise RejectorError(f"input row {index}: missing field {fields}")
        rendered.append(_render(task.prompt, row))
    return rendered


def _placeholders(template: str) -> set[str]:
    try:
        return {name for _, name, _, _ in Formatter().parse(template) if name}
    except ValueError as exc:
        raise RejectorError(f"prompt template is malformed: {exc}") from None


def _render(prompt: PromptConfig, row: dict[str, Any]) -> list[Message]:
    templates = (("system", prompt.system), ("user", prompt.user))
    return [{"role": role, "content": text.format_map(row)} for role, text in templates if text]


def write_results(path: str, results: Iterable[dict[str, Any]]) -> None:
    """Write one JSON object per line, overwriting any existing file."""
    with open(path, "w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result) + "\n")
