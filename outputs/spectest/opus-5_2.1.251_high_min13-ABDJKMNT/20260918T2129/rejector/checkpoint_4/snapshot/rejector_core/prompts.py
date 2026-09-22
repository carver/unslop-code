"""Chat message assembly and the row fields a task needs."""

from __future__ import annotations

from collections.abc import Sequence

from .config import Evaluation, Prompt, TaskConfig
from .errors import InputError
from .icl import IclExample
from .templates import placeholders, render


def build_messages(
    prompt: Prompt,
    row: dict,
    response: str | None = None,
    examples: Sequence[IclExample] = (),
) -> list[dict]:
    """Render the chat messages for one input row.

    In-context examples sit between the system message and the row's own
    question, replayed as the user turn that asked for them and the assistant
    turn that answered.
    """
    messages = []
    if prompt.system is not None:
        messages.append({"role": "system", "content": render(prompt.system, row, response)})
    for example in examples:
        messages.append({"role": "user", "content": render(prompt.user, example.input)})
        messages.append({"role": "assistant", "content": example.output})
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
