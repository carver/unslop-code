"""Prompt template rendering and the per-row field requirements it implies."""

from __future__ import annotations

import re
from typing import Any, Iterator, Mapping, Sequence

from .config import PromptConfig, TaskConfig
from .errors import ConfigError
from .icl import IclExample

# Only the documented `{field}` form is a placeholder; any other brace (JSON
# examples, LaTeX) is left untouched.
PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

# The generated response, available to judge prompts and script commands.
RESPONSE_FIELD = "__response__"


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


def render_messages(
    prompt: PromptConfig,
    row: Mapping[str, Any],
    examples: Sequence[IclExample] = (),
) -> list[dict[str, str]]:
    """Render a system/user prompt pair into chat messages.

    ICL demonstrations sit between the system message and the row's own user
    message, as alternating user/assistant turns; each example input goes
    through the same user template as the row, and its output is verbatim.
    """
    messages = []
    if prompt.system is not None:
        messages.append({"role": "system", "content": render(prompt.system, row)})
    for example in examples:
        messages.append({"role": "user", "content": render(prompt.user, example.input)})
        messages.append({"role": "assistant", "content": example.output})
    messages.append({"role": "user", "content": render(prompt.user, row)})
    return messages


def required_fields(config: TaskConfig) -> list[str]:
    """Fields every row must carry: template placeholders plus the answer field."""
    fields = [
        field
        for template in _row_templates(config)
        for field in template_fields(template)
        if field != RESPONSE_FIELD
    ]
    if config.evaluation and config.evaluation.answer_field:
        fields.append(config.evaluation.answer_field)
    return list(dict.fromkeys(fields))


def _row_templates(config: TaskConfig) -> Iterator[str]:
    """Every template rendered against an input row, prompts and evaluation alike."""
    yield config.prompt.user
    yield config.prompt.system or ""
    evaluation = config.evaluation
    if evaluation and evaluation.judge:
        yield evaluation.judge.prompt.user
        yield evaluation.judge.prompt.system or ""
    if evaluation and evaluation.script:
        yield evaluation.script.command_template


def validate_examples(config: TaskConfig, label: str = "") -> None:
    """Fail before any API traffic if a demonstration cannot be rendered."""
    fields = template_fields(config.prompt.user)
    prefix = f"task '{label}': " if label else ""
    for setup in config.icl.setups if config.icl else ():
        for index, example in enumerate(setup.examples):
            for field in fields:
                if field not in example.input:
                    raise ConfigError(
                        f"{prefix}icl setup '{setup.name}' example {index}: "
                        f"missing field '{field}'"
                    )


def validate_rows(
    rows: Sequence[Mapping[str, Any]], config: TaskConfig, label: str = ""
) -> None:
    """Fail before any API traffic if a row is missing a field the task needs.

    `label` names the task in the error when a run covers more than one.
    """
    fields = required_fields(config)
    prefix = f"task '{label}': " if label else ""
    for index, row in enumerate(rows):
        for field in fields:
            if field not in row:
                raise ConfigError(f"{prefix}row {index}: missing field '{field}'")
