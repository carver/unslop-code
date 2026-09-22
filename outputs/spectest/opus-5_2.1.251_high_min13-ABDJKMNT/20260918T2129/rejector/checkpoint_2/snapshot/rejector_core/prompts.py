"""Template rendering and the row fields a task needs."""

from __future__ import annotations

import re

from .config import Evaluation, Prompt, TaskConfig
from .errors import InputError

RESPONSE_FIELD = "__response__"
RESPONSE_PLACEHOLDER = f"{{{RESPONSE_FIELD}}}"

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def placeholders(template: str) -> list[str]:
    """Row field names referenced by a template, in order of appearance."""
    return [name for name in _PLACEHOLDER.findall(template) if name != RESPONSE_FIELD]


def render(template: str, row: dict, response: str | None = None) -> str:
    """Substitute `{field}` placeholders with the row's values.

    `{__response__}` is only resolved when a `response` is supplied, and it is
    resolved after the row fields, so a field whose own value contains the
    marker — such as a `test_code` column — is expanded too.
    """
    rendered = _PLACEHOLDER.sub(
        lambda match: match.group(0) if match.group(1) == RESPONSE_FIELD else str(row[match.group(1)]),
        template,
    )
    return rendered if response is None else rendered.replace(RESPONSE_PLACEHOLDER, response)


def build_messages(prompt: Prompt, row: dict, response: str | None = None) -> list[dict]:
    """Render the chat messages for one input row."""
    messages = []
    if prompt.system is not None:
        messages.append({"role": "system", "content": render(prompt.system, row, response)})
    messages.append({"role": "user", "content": render(prompt.user, row, response)})
    return messages


def required_fields(task: TaskConfig) -> list[str]:
    """Every row field the task reads, across its prompt and its evaluation."""
    fields = _prompt_fields(task.prompt)
    if task.evaluation:
        fields += _evaluation_fields(task.evaluation)
    return list(dict.fromkeys(fields))


def validate_rows(rows: list[dict], fields: list[str]) -> None:
    """Fail on the first row missing a field the task needs."""
    for index, row in enumerate(rows):
        for field in fields:
            if field not in row:
                raise InputError(f"input row {index} is missing field '{field}'")


def _prompt_fields(prompt: Prompt) -> list[str]:
    return placeholders(prompt.user) + placeholders(prompt.system or "")


def _evaluation_fields(evaluation: Evaluation) -> list[str]:
    """Fields read while judging: the answer column, commands, judge prompts."""
    fields = [evaluation.answer_field] if evaluation.answer_field else []
    if evaluation.command_template:
        fields += placeholders(evaluation.command_template)
    if evaluation.judge_prompt:
        fields += _prompt_fields(evaluation.judge_prompt)
    return fields
