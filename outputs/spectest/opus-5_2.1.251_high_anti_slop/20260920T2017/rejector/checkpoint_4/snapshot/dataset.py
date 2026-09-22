"""Reading JSONL input rows, rendering their templates, and writing results."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config import EvaluationConfig, TaskConfig
from errors import InputError
from prompts import RESPONSE_FIELD, RenderedPrompt, render, template_fields


def load_rows(path: str) -> list[dict[str, Any]]:
    """Read a JSONL file into a list of objects, preserving file order."""
    try:
        lines = Path(path).read_text().splitlines()
    except OSError as exc:
        raise InputError(f"cannot read input {path}: {exc}") from exc

    rows = []
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        rows.append(_parse_row(line, index))
    return rows


def _parse_row(line: str, index: int) -> dict[str, Any]:
    try:
        row = json.loads(line)
    except json.JSONDecodeError as exc:
        raise InputError(f"row {index}: invalid JSON: {exc}") from exc
    if not isinstance(row, dict):
        raise InputError(f"row {index}: expected a JSON object")
    return row


def prepare_prompts(rows: list[dict[str, Any]], config: TaskConfig) -> list[RenderedPrompt]:
    """Render every row's prompts and check the fields the evaluation needs.

    Doing this up front means a row missing a field fails before any request is
    sent, rather than half way through a run. The evaluation's own templates —
    a judge prompt or a script command — are checked here too, as they are only
    rendered once a response exists.

    Raises:
        InputError: a row is missing a field one of the task's templates needs.
    """
    required = _evaluation_fields(config.evaluation)
    prompts = []
    for index, row in enumerate(rows):
        prompt = RenderedPrompt(
            system=_render_row(config.prompt.system, row, index),
            user=_render_row(config.prompt.user, row, index),
        )
        missing = sorted(required - row.keys())
        if missing:
            raise InputError(f"row {index}: missing field '{missing[0]}' required by the evaluation")
        prompts.append(prompt)
    return prompts


def _evaluation_fields(evaluation: EvaluationConfig | None) -> set[str]:
    """Row fields the evaluation reads, excluding the response placeholder."""
    if evaluation is None:
        return set()
    templates = [evaluation.command_template] if evaluation.command_template else []
    if evaluation.judge_prompt:
        templates += [evaluation.judge_prompt.system, evaluation.judge_prompt.user]
    fields = {field for template in templates for field in template_fields(template)}
    fields.discard(RESPONSE_FIELD)
    return fields | ({evaluation.answer_field} if evaluation.answer_field else set())


def _render_row(template: str, row: dict[str, Any], index: int) -> str:
    missing = sorted(template_fields(template) - row.keys())
    if missing:
        raise InputError(f"row {index}: missing field '{missing[0]}' required by the prompt template")
    return render(template, row)


def write_results(path: str, records: list[dict[str, Any]]) -> None:
    """Write one JSON object per line, creating or overwriting the file."""
    with open(path, "w") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
