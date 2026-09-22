"""Reading the JSONL input file and rendering prompt templates."""

from __future__ import annotations

import json
from pathlib import Path
from string import Formatter

from .config import JudgeConfig, TaskConfig
from .errors import InputError
from .icl import IclSetup

RESPONSE_FIELD = "__response__"
RESPONSE_PLACEHOLDER = "{" + RESPONSE_FIELD + "}"


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


def render_template(template: str, row: dict, response: str | None = None) -> str:
    """Fill a template from the row, plus `{__response__}` once one exists."""
    values = row if response is None else {**row, RESPONSE_FIELD: response}
    return template.format(**values)


def required_fields(config: TaskConfig) -> list[str]:
    """Row fields the task needs: every placeholder plus the answer field.

    `__response__` is supplied by the run rather than the row, so it is not
    required of the input.
    """
    templates = [config.system_template, config.user_template]
    evaluation = config.evaluation
    if evaluation and evaluation.script:
        templates.append(evaluation.script.command_template)
    if evaluation and evaluation.judge:
        templates += [evaluation.judge.system_template, evaluation.judge.user_template]

    fields = [
        name
        for template in templates
        for name in template_fields(template)
        if name != RESPONSE_FIELD
    ]
    if config.answer_field:
        fields.append(config.answer_field)
    return fields


def validate_rows(rows: list[dict], config: TaskConfig) -> None:
    """Fail the run if any row lacks a placeholder field or the answer field."""
    required = required_fields(config)
    for index, row in enumerate(rows):
        for name in required:
            if name not in row:
                raise InputError(f"row {index}: missing field {name!r}")


def render_messages(
    row: dict, config: TaskConfig, setup: IclSetup | None = None
) -> list[dict]:
    """Build the chat messages for `row`, with any ICL turns before its own.

    The examples sit between the system message and the row's user message, so
    the model sees them as completed exchanges.
    """
    messages = _messages(config.system_template, config.user_template, row)
    if setup is None:
        return messages
    return messages[:-1] + list(setup.messages) + messages[-1:]


def render_judge_messages(judge: JudgeConfig, row: dict, response: str) -> list[dict]:
    """Build the judge's chat messages, with `__response__` filled in."""
    return _messages(judge.system_template, judge.user_template, row, response)


def _messages(
    system: str | None, user: str, row: dict, response: str | None = None
) -> list[dict]:
    messages = []
    if system is not None:
        content = render_template(system, row, response)
        messages.append({"role": "system", "content": content})
    messages.append({"role": "user", "content": render_template(user, row, response)})
    return messages
