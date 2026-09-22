"""Input loading and template rendering, both validated before any request is sent."""

import json
from typing import Any, Mapping

from chat_templates import Messages
from config import EvaluationConfig, PromptConfig, TaskConfig
from errors import InputError
from templates import RESPONSE_KEY, render_template

Row = dict[str, Any]


def load_rows(path: str) -> list[Row]:
    """Read a JSONL file into a list of rows, preserving file order."""
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError as exc:
        raise InputError(f"cannot read input file {path}: {exc}") from exc

    rows = []
    for number, line in enumerate(lines, start=1):
        if line.strip():
            rows.append(_parse_row(path, number, line))
    return rows


def build_prompts(rows: list[Row], task: TaskConfig) -> list[Messages]:
    """Render the chat messages for every row and check the fields its evaluation will need."""
    prompts = []
    for index, row in enumerate(rows):
        _check_evaluation_fields(task.evaluation, row, index)
        prompts.append(render_messages(task.prompt, row, f"row {index} prompt template"))
    return prompts


def render_messages(prompt: PromptConfig, values: Mapping[str, Any], context: str) -> Messages:
    """Render a prompt's optional system message and its user message from ``values``."""
    messages = []
    if prompt.system:
        messages.append({"role": "system", "content": render_template(prompt.system, values, context)})
    messages.append({"role": "user", "content": render_template(prompt.user, values, context)})
    return messages


def _parse_row(path: str, number: int, line: str) -> Row:
    try:
        row = json.loads(line)
    except json.JSONDecodeError as exc:
        raise InputError(f"{path}: line {number} is not valid JSON: {exc.msg}") from exc
    if not isinstance(row, dict):
        raise InputError(f"{path}: line {number} is not a JSON object")
    return row


def _check_evaluation_fields(evaluation: EvaluationConfig | None, row: Row, index: int) -> None:
    """Render the evaluation's templates against the row so missing fields fail before the run."""
    if evaluation is None:
        return
    if evaluation.answer_field is not None and evaluation.answer_field not in row:
        raise InputError(f"row {index} is missing field '{evaluation.answer_field}' required by the evaluation")

    probe = {**row, RESPONSE_KEY: ""}
    if evaluation.judge_prompt is not None:
        render_messages(evaluation.judge_prompt, probe, f"row {index} judge prompt template")
    if evaluation.command_template is not None:
        render_template(evaluation.command_template, probe, f"row {index} command template")
