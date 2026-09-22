"""Rendering of prompt and command templates against input rows."""

from __future__ import annotations

from string import Formatter

from config import Prompt
from errors import UsageError

# Placeholder standing for the generated response in judge prompts and commands.
RESPONSE = "__response__"


def render_all(prompt: Prompt, rows: list[dict]) -> list[list[dict]]:
    """Render chat messages for every row so template errors surface before any API call."""
    return [messages(prompt, row, index) for index, row in enumerate(rows)]


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
    rendered = []
    if prompt.system:
        rendered.append(
            {"role": "system", "content": render(prompt.system, values, row_index, f"{where}.system")}
        )
    rendered.append(
        {"role": "user", "content": render(prompt.user, values, row_index, f"{where}.user")}
    )
    return rendered


def render(template: str, values: dict, row_index: int, where: str) -> str:
    """Substitute `{field}` placeholders, naming the row when one is missing."""
    require_fields(template, values, row_index, where)
    return template.format(**values)


def require_fields(template: str, values: dict, row_index: int, where: str) -> None:
    """Fail fast when a template references something the row does not carry."""
    for _, field, _, _ in Formatter().parse(template):
        if field and field not in values:
            raise UsageError(f"row {row_index}: {where} references missing field '{field}'")
