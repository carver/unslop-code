"""Reading the JSONL input file and rendering prompt templates."""

from __future__ import annotations

import json
from pathlib import Path
from string import Formatter

from .config import TaskConfig


class InputError(Exception):
    """A bad input file or a row that cannot satisfy the task; exit code 1."""


def load_rows(path: Path) -> list[dict]:
    """Parse the JSONL input file into a list of row objects."""
    try:
        lines = path.read_text().splitlines()
    except FileNotFoundError as exc:
        raise InputError(f"input file not found: {path}") from exc

    rows = []
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise InputError(f"row {index}: invalid JSON ({exc.msg})") from exc
        if not isinstance(row, dict):
            raise InputError(f"row {index}: expected a JSON object")
        rows.append(row)
    return rows


def template_fields(template: str | None) -> list[str]:
    """The `{field}` placeholder names referenced by a template."""
    if template is None:
        return []
    return [name for _, name, _, _ in Formatter().parse(template) if name]


def validate_rows(rows: list[dict], config: TaskConfig) -> None:
    """Fail the run if any row lacks a prompt placeholder or the answer field."""
    required = template_fields(config.system_template) + template_fields(
        config.user_template
    )
    if config.answer_field:
        required.append(config.answer_field)

    for index, row in enumerate(rows):
        for name in required:
            if name not in row:
                raise InputError(f"row {index}: missing field {name!r}")


def render_messages(row: dict, config: TaskConfig) -> list[dict]:
    """Build the chat messages for `row` from the configured templates."""
    messages = []
    if config.system_template is not None:
        messages.append(
            {"role": "system", "content": config.system_template.format(**row)}
        )
    messages.append({"role": "user", "content": config.user_template.format(**row)})
    return messages
