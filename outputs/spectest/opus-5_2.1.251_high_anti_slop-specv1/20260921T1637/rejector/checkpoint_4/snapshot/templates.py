"""Rendering of the ``{field}`` templates used by prompts, ICL examples, and commands."""

from typing import Any, Mapping

from errors import InputError

#: Template placeholder standing for the generated response in evaluation templates.
RESPONSE_KEY = "__response__"


def render_template(template: str, values: Mapping[str, Any], context: str) -> str:
    """Fill ``{field}`` placeholders from ``values``; ``context`` names the template in errors."""
    try:
        return template.format_map(values)
    except KeyError as exc:
        raise InputError(f"{context} is missing field '{exc.args[0]}'") from exc
