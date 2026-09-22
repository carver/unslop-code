"""Answer extraction and response evaluation."""

from __future__ import annotations

import re
from dataclasses import dataclass

from client import ApiClient
from config import Evaluation
from errors import UsageError
from prompts import RESPONSE, messages, render, require_fields
from shell import run_command

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_CHOICE = re.compile(r"\b[A-D]\b")


@dataclass(frozen=True)
class Verdict:
    """The judgement on one response. `passed` is None when no evaluation is configured."""

    passed: bool | None
    extracted: str | None
    judge_score: float | None = None
    judge_meta: dict | None = None


async def evaluate(
    evaluation: Evaluation | None, text: str, row: dict, row_index: int, client: ApiClient
) -> Verdict:
    """Judge one response, making the API or shell call the evaluation type needs."""
    if evaluation is None:
        return Verdict(None, None)
    if evaluation.type == "script":
        return await _script(evaluation, text, row, row_index)
    if evaluation.type == "llm_judge":
        return await _llm_judge(evaluation, text, row, row_index, client)
    return _LOCAL_EVALUATORS[evaluation.type](evaluation, text, row)


def extract(text: str, method: str) -> str | None:
    """Pull the comparison value out of a response."""
    return _EXTRACTORS[method](text)


def require_row_fields(evaluation: Evaluation | None, rows: list[dict]) -> None:
    """Fail fast when a row lacks something the evaluation needs."""
    if evaluation is None:
        return
    templates = _templates(evaluation)
    for index, row in enumerate(rows):
        if evaluation.answer_field is not None and evaluation.answer_field not in row:
            raise UsageError(f"row {index}: missing evaluation field '{evaluation.answer_field}'")
        for where, template in templates:
            # The response is only known once the row runs, so stand in for it here.
            require_fields(template, {**row, RESPONSE: ""}, f"row {index}: {where}")


def _templates(evaluation: Evaluation) -> list[tuple[str, str]]:
    """The evaluation's own templates, labelled for error messages."""
    labelled = {"evaluation.command_template": evaluation.command_template}
    if evaluation.judge_prompt is not None:
        labelled["evaluation.judge_prompt.system"] = evaluation.judge_prompt.system
        labelled["evaluation.judge_prompt.user"] = evaluation.judge_prompt.user
    return [(where, template) for where, template in labelled.items() if template]


def _last_number(text: str) -> str | None:
    numbers = _NUMBER.findall(text)
    return numbers[-1] if numbers else None


def _first_number(text: str) -> str | None:
    match = _NUMBER.search(text)
    return match[0] if match else None


def _letter(text: str) -> str | None:
    """The first standalone A-D choice, covering `A`, `(A)`, `A)` and `Answer: A`."""
    match = _CHOICE.search(text)
    return match[0] if match else None


def _last_line(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else None


_EXTRACTORS = {
    "last_number": _last_number,
    "first_number": _first_number,
    "last_line": _last_line,
    "letter": _letter,
    "full": str.strip,
}


def _exact_match(evaluation: Evaluation, text: str, row: dict) -> Verdict:
    extracted = extract(text, evaluation.extract)
    expected = str(row[evaluation.answer_field]).strip()
    return Verdict(extracted == expected, extracted)


def _contains(evaluation: Evaluation, text: str, row: dict) -> Verdict:
    expected = str(row[evaluation.answer_field])
    found = expected in text
    return Verdict(found, expected if found else None)


def _regex(evaluation: Evaluation, text: str, row: dict) -> Verdict:
    match = evaluation.pattern.search(text)
    if match is None:
        return Verdict(False, None)
    # A capturing group names the answer explicitly; otherwise the whole match is it.
    return Verdict(True, match[1] if match.groups() else match[0])


async def _script(evaluation: Evaluation, text: str, row: dict, row_index: int) -> Verdict:
    """Pass when the rendered command exits with the configured code."""
    command = render(
        evaluation.command_template,
        {**row, RESPONSE: text},
        f"row {row_index}: evaluation.command_template",
    )
    # A row field can expand to text that itself carries the placeholder.
    command = command.replace(f"{{{RESPONSE}}}", text)
    return Verdict(await run_command(command) == evaluation.success_exit_code, None)


async def _llm_judge(
    evaluation: Evaluation, text: str, row: dict, row_index: int, client: ApiClient
) -> Verdict:
    """Ask the judge model to score the response and compare that score to the threshold."""
    attempt = await client.complete(
        messages(
            evaluation.judge_prompt, row, row_index, response=text, where="evaluation.judge_prompt"
        ),
        model=evaluation.model,
        temperature=0.0,
    )
    if attempt.text is None:
        return Verdict(False, None)
    extracted = extract(attempt.text, evaluation.extract)
    score = _score(extracted)
    return Verdict(
        passed=score is not None and score >= evaluation.threshold,
        extracted=extracted,
        judge_score=score,
        judge_meta=attempt.meta,
    )


def _score(extracted: str | None) -> float | None:
    """The judge's numeric score; None when its reply did not carry one."""
    if extracted is None:
        return None
    try:
        score = float(extracted)
    except ValueError:
        return None
    return int(score) if score.is_integer() else score


_LOCAL_EVALUATORS = {
    "exact_match": _exact_match,
    "contains": _contains,
    "regex": _regex,
}