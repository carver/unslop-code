"""Prompt templates and the chat messages one request is built from."""

from __future__ import annotations

import string
from dataclasses import dataclass
from typing import Any, Mapping

#: Placeholder that evaluation templates use for the generated response.
RESPONSE_FIELD = "__response__"

_FORMATTER = string.Formatter()


@dataclass(frozen=True)
class RenderedPrompt:
    """The messages of a single request.

    `examples` holds the in-context learning pairs that sit between the system
    message and the row's own user message, as `(user, assistant)` turns; it is
    empty when no ICL setup applies.
    """

    system: str
    user: str
    examples: tuple[tuple[str, str], ...] = ()

    def messages(self) -> list[dict[str, str]]:
        """The chat messages in the order the API expects them."""
        messages = [{"role": "system", "content": self.system}]
        for user, assistant in self.examples:
            messages.append({"role": "user", "content": user})
            messages.append({"role": "assistant", "content": assistant})
        messages.append({"role": "user", "content": self.user})
        return messages


def template_fields(template: str) -> set[str]:
    """The `{field}` names a template substitutes."""
    return {field for _, field, _, _ in _FORMATTER.parse(template) if field}


def render(template: str, values: Mapping[str, Any]) -> str:
    """Substitute a template's placeholders; every field must be present."""
    return template.format_map(values)
