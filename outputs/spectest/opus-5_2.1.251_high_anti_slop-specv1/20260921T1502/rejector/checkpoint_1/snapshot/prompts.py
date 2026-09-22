"""Rendering of prompt templates against input rows."""

from __future__ import annotations

from string import Formatter

from config import Prompt
from errors import UsageError


def render_all(prompt: Prompt, rows: list[dict]) -> list[list[dict]]:
    """Render chat messages for every row so template errors surface before any API call."""
    return [_messages(prompt, row, index) for index, row in enumerate(rows)]


def _messages(prompt: Prompt, row: dict, row_index: int) -> list[dict]:
    """Chat messages for one row; the system message is omitted when not configured."""
    messages = []
    if prompt.system:
        messages.append({"role": "system", "content": _render(prompt.system, row, row_index, "system")})
    messages.append({"role": "user", "content": _render(prompt.user, row, row_index, "user")})
    return messages


def _render(template: str, row: dict, row_index: int, where: str) -> str:
    for field in _placeholders(template):
        if field not in row:
            raise UsageError(
                f"row {row_index}: prompt.{where} references missing field '{field}'"
            )
    return template.format(**row)


def _placeholders(template: str) -> list[str]:
    """Placeholder names referenced by a template."""
    return [field for _, field, _, _ in Formatter().parse(template) if field]
