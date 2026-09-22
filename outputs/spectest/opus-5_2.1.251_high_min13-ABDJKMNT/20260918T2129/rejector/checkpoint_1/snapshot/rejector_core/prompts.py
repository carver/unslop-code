"""Prompt rendering and the row fields a task needs."""

from __future__ import annotations

import re

from .config import TaskConfig
from .errors import InputError

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def placeholders(template: str) -> list[str]:
    """Field names referenced by a template, in order of appearance."""
    return _PLACEHOLDER.findall(template)


def required_fields(task: TaskConfig) -> list[str]:
    """Every row field the task reads: prompt placeholders plus answer_field."""
    fields = placeholders(task.prompt.user)
    if task.prompt.system:
        fields += placeholders(task.prompt.system)
    if task.evaluation and task.evaluation.answer_field:
        fields.append(task.evaluation.answer_field)
    return list(dict.fromkeys(fields))


def validate_rows(rows: list[dict], fields: list[str]) -> None:
    """Fail on the first row missing a field the task needs."""
    for index, row in enumerate(rows):
        for field in fields:
            if field not in row:
                raise InputError(f"input row {index} is missing field '{field}'")


def render(template: str, row: dict) -> str:
    """Substitute `{field}` placeholders with the row's values."""
    return _PLACEHOLDER.sub(lambda match: str(row[match.group(1)]), template)


def build_messages(task: TaskConfig, row: dict) -> list[dict]:
    """Render the chat messages for one input row."""
    messages = []
    if task.prompt.system is not None:
        messages.append({"role": "system", "content": render(task.prompt.system, row)})
    messages.append({"role": "user", "content": render(task.prompt.user, row)})
    return messages
