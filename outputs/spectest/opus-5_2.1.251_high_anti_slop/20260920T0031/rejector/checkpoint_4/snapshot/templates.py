"""Prompt templates and the `{field}` substitution they share.

Task prompts, judge prompts and script commands all use the same syntax:
`{field}` is replaced with the value of that field in the input row, and
`{__response__}` with the generated response text.
"""

from __future__ import annotations

from dataclasses import dataclass
from string import Formatter
from typing import Any

from errors import RejectorError

#: One chat turn; tool turns carry more than text, so values are not all strings.
Message = dict[str, Any]

#: Placeholder carrying the generated response into judge prompts and script commands.
RESPONSE = "__response__"
RESPONSE_TOKEN = "{" + RESPONSE + "}"


@dataclass(frozen=True)
class PromptConfig:
    """System and user templates; an empty system template is left out of the request."""

    system: str
    user: str


def placeholders(*templates: str) -> set[str]:
    """Row fields the templates reference, ignoring the response placeholder."""
    names: set[str] = set()
    for template in templates:
        try:
            names.update(name for _, name, _, _ in Formatter().parse(template) if name)
        except ValueError as exc:
            raise RejectorError(f"template is malformed: {exc}") from None
    return names - {RESPONSE}


def render(prompt: PromptConfig, values: dict[str, Any]) -> list[Message]:
    """Render a prompt into chat messages."""
    templates = (("system", prompt.system), ("user", prompt.user))
    return [{"role": role, "content": text.format_map(values)} for role, text in templates if text]


def render_command(template: str, row: dict[str, Any], response: str) -> str:
    """Expand row fields first, then every `{__response__}` — including ones a row field brought in."""
    expanded = template.format_map({**row, RESPONSE: RESPONSE_TOKEN})
    return expanded.replace(RESPONSE_TOKEN, response)
