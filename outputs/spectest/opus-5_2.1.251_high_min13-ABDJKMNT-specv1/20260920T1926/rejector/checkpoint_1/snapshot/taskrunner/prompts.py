"""Prompt template rendering and the per-row field requirements it implies."""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence

from .config import ConfigError, TaskConfig

# Only the documented `{field}` form is a placeholder; any other brace (JSON
# examples, LaTeX) is left untouched.
PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


class MissingFieldError(Exception):
    """A template referenced a field the input row does not have."""

    def __init__(self, field: str) -> None:
        super().__init__(f"missing field '{field}'")
        self.field = field


def template_fields(template: str) -> list[str]:
    """The placeholder names used by a template, in first-appearance order."""
    return list(dict.fromkeys(PLACEHOLDER.findall(template)))


def render(template: str, row: Mapping[str, Any]) -> str:
    """Substitute `{field}` placeholders with the row's values."""

    def substitute(match: re.Match[str]) -> str:
        field = match.group(1)
        if field not in row:
            raise MissingFieldError(field)
        return str(row[field])

    return PLACEHOLDER.sub(substitute, template)


def build_messages(config: TaskConfig, row: Mapping[str, Any]) -> list[dict[str, str]]:
    """Render the chat messages for one input row."""
    messages = []
    if config.prompt.system is not None:
        messages.append({"role": "system", "content": render(config.prompt.system, row)})
    messages.append({"role": "user", "content": render(config.prompt.user, row)})
    return messages


def required_fields(config: TaskConfig) -> list[str]:
    """Fields every row must carry: prompt placeholders plus the answer field."""
    templates = [config.prompt.user, config.prompt.system or ""]
    fields = [field for template in templates for field in template_fields(template)]
    if config.evaluation and config.evaluation.answer_field:
        fields.append(config.evaluation.answer_field)
    return list(dict.fromkeys(fields))


def validate_rows(rows: Sequence[Mapping[str, Any]], config: TaskConfig) -> None:
    """Fail before any API traffic if a row is missing a field the task needs."""
    fields: Iterable[str] = required_fields(config)
    for index, row in enumerate(rows):
        for field in fields:
            if field not in row:
                raise ConfigError(f"row {index}: missing field '{field}'")
