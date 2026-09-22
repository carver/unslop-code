"""Rendering of prompt, ICL example and command templates against input rows."""

from __future__ import annotations

from string import Formatter

from config import Prompt
from errors import UsageError
from icl import Icl, Setup

# Placeholder standing for the generated response in judge prompts and commands.
RESPONSE = "__response__"


def render_all(prompt: Prompt, rows: list[dict]) -> list[list[dict]]:
    """Render chat messages for every row so template errors surface before any API call."""
    return [messages(prompt, row, index) for index, row in enumerate(rows)]


def render_examples(prompt: Prompt, icl: Icl | None) -> dict[str, list[dict]]:
    """The example turns of each setup, keyed by setup name.

    Examples do not depend on the input row, so every row of a task replays the
    same turns: each example's input through the user template, then its output
    verbatim as the assistant's reply.
    """
    if icl is None:
        return {}
    return {setup.name: _example_turns(prompt, setup) for setup in icl.setups}


def _example_turns(prompt: Prompt, setup: Setup) -> list[dict]:
    turns = []
    for index, example in enumerate(setup.examples):
        where = f"icl setup '{setup.name}' example {index}: prompt.user"
        turns.append({"role": "user", "content": render(prompt.user, example.input, where)})
        turns.append({"role": "assistant", "content": example.output})
    return turns


def messages(
    prompt: Prompt,
    row: dict,
    row_index: int,
    response: str | None = None,
    where: str = "prompt",
) -> list[dict]:
    """Chat messages for one row; the system message is omitted when not configured.

    `response` fills the `{__response__}` placeholder that judge prompts use, and
    `where` labels the prompt in error messages.
    """
    values = row if response is None else {**row, RESPONSE: response}
    label = f"row {row_index}: {where}"
    rendered = []
    if prompt.system:
        rendered.append({"role": "system", "content": render(prompt.system, values, f"{label}.system")})
    rendered.append({"role": "user", "content": render(prompt.user, values, f"{label}.user")})
    return rendered


def render(template: str, values: dict, where: str) -> str:
    """Substitute `{field}` placeholders, naming the template when one is missing."""
    require_fields(template, values, where)
    return template.format(**values)


def require_fields(template: str, values: dict, where: str) -> None:
    """Fail fast when a template references something the values do not carry."""
    for _, field, _, _ in Formatter().parse(template):
        if field and field not in values:
            raise UsageError(f"{where} references missing field '{field}'")
