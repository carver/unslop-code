"""Prompt template rendering and the per-row field requirements it implies."""

from __future__ import annotations

import re

from rejlib.config import TaskConfig
from rejlib.errors import ConfigError

# `{field}` placeholders only: brace text containing quotes, colons or spaces is
# literal, so prompts may embed JSON or code without escaping (T17).
PLACEHOLDER = re.compile(r"\{([A-Za-z0-9_.\-]+)\}")


def placeholders(template: str) -> list[str]:
    """Field names referenced by a template, in first-appearance order."""
    return list(dict.fromkeys(PLACEHOLDER.findall(template)))


def render(template: str, row: dict) -> str:
    """Substitute every ``{field}`` placeholder with the row's value."""
    return PLACEHOLDER.sub(lambda match: str(row[match.group(1)]), template)


def build_messages(config: TaskConfig, row: dict) -> list[dict]:
    """The ``messages`` array for one row; the system message is optional (T16)."""
    messages = []
    if config.system_prompt:
        messages.append({"role": "system", "content": render(config.system_prompt, row)})
    messages.append({"role": "user", "content": render(config.user_prompt, row)})
    return messages


def required_fields(config: TaskConfig) -> list[str]:
    """Fields every input row must carry: prompt placeholders plus answer_field."""
    fields = placeholders(config.user_prompt)
    if config.system_prompt:
        fields += placeholders(config.system_prompt)
    if config.evaluation and config.evaluation.answer_field:
        fields.append(config.evaluation.answer_field)
    return list(dict.fromkeys(fields))


def validate_rows(rows: list[dict], config: TaskConfig) -> None:
    """Fail before any request is sent if a row lacks a field the task needs (T10)."""
    fields = required_fields(config)
    for index, row in enumerate(rows):
        for field in fields:
            if field not in row:
                raise ConfigError(f"row {index}: missing field '{field}'")
