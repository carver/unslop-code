"""Prompt template rendering and the per-row field requirements it implies."""

from __future__ import annotations

import re

from rejlib.config import JudgeSpec, TaskConfig
from rejlib.errors import ConfigError

# `{field}` placeholders only: brace text containing quotes, colons or spaces is
# literal, so prompts may embed JSON or code without escaping (T17).
PLACEHOLDER = re.compile(r"\{([A-Za-z0-9_.\-]+)\}")

#: Placeholder bound to the generated response rather than to an input row field.
RESPONSE_FIELD = "__response__"


def placeholders(template: str) -> list[str]:
    """Field names referenced by a template, in first-appearance order."""
    return list(dict.fromkeys(PLACEHOLDER.findall(template)))


def render(template: str, row: dict) -> str:
    """Substitute every ``{field}`` placeholder with the row's value."""
    return PLACEHOLDER.sub(lambda match: str(row[match.group(1)]), template)


def render_with_response(template: str, row: dict, response: str) -> str:
    """Render ``template`` against ``row``, then substitute ``__response__``.

    Row fields expand first, so a ``{__response__}`` that a field's own text
    introduces is substituted as well (T23).
    """
    expanded = PLACEHOLDER.sub(
        lambda match: match.group(0) if match.group(1) == RESPONSE_FIELD
        else str(row[match.group(1)]),
        template,
    )
    return expanded.replace("{" + RESPONSE_FIELD + "}", response)


def build_messages(config: TaskConfig, row: dict) -> list[dict]:
    """The ``messages`` array for one row; the system message is optional (T16)."""
    system = render(config.system_prompt, row) if config.system_prompt else None
    return _messages(system, render(config.user_prompt, row))


def judge_messages(judge: JudgeSpec, row: dict, response: str) -> list[dict]:
    """The judge call's ``messages``, with ``__response__`` bound to the response."""
    system = (
        render_with_response(judge.system_prompt, row, response)
        if judge.system_prompt else None
    )
    return _messages(system, render_with_response(judge.user_prompt, row, response))


def _messages(system: str | None, user: str) -> list[dict]:
    messages = [{"role": "user", "content": user}]
    if system:
        messages.insert(0, {"role": "system", "content": system})
    return messages


def required_fields(config: TaskConfig) -> list[str]:
    """Fields every input row must carry: template placeholders plus answer_field."""
    fields = []
    for template in _row_templates(config):
        fields += [name for name in placeholders(template) if name != RESPONSE_FIELD]
    if config.evaluation and config.evaluation.answer_field:
        fields.append(config.evaluation.answer_field)
    return list(dict.fromkeys(fields))


def _row_templates(config: TaskConfig) -> list[str]:
    """Every template the task renders against an input row."""
    templates = [config.user_prompt, config.system_prompt]
    evaluation = config.evaluation
    if evaluation and evaluation.script:
        templates.append(evaluation.script.command_template)
    if evaluation and evaluation.judge:
        templates += [evaluation.judge.user_prompt, evaluation.judge.system_prompt]
    return [template for template in templates if template]


def validate_rows(rows: list[dict], config: TaskConfig) -> None:
    """Fail before any request is sent if a row lacks a field the task needs (T10)."""
    fields = required_fields(config)
    for index, row in enumerate(rows):
        for field in fields:
            if field not in row:
                raise ConfigError(f"row {index}: missing field '{field}'")
