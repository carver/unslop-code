"""`{field}` template rendering, shared by prompts, evaluation, and ICL."""

from __future__ import annotations

import re

RESPONSE_FIELD = "__response__"
RESPONSE_PLACEHOLDER = f"{{{RESPONSE_FIELD}}}"

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def placeholders(template: str) -> list[str]:
    """Row field names referenced by a template, in order of appearance."""
    return [name for name in _PLACEHOLDER.findall(template) if name != RESPONSE_FIELD]


def render(template: str, row: dict, response: str | None = None) -> str:
    """Substitute `{field}` placeholders with the row's values.

    `{__response__}` is only resolved when a `response` is supplied, and it is
    resolved after the row fields, so a field whose own value contains the
    marker — such as a `test_code` column — is expanded too.
    """
    rendered = _PLACEHOLDER.sub(
        lambda match: match.group(0) if match.group(1) == RESPONSE_FIELD else str(row[match.group(1)]),
        template,
    )
    return rendered if response is None else rendered.replace(RESPONSE_PLACEHOLDER, response)
