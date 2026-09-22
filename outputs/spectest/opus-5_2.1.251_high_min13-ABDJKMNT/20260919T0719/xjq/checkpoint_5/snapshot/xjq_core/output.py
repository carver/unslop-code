"""Choosing how an evaluated query result is written to stdout.

The output flags are ranked: `--text-all`, then `--text`, then `--json`, then
the auto-formatting that `render` applies on its own. Each of the first three
only reaches a result it has something to do with -- a node set of elements --
which is why `--json` is invisible for a `text()` or attribute query.
"""

from dataclasses import dataclass

from .export import export
from .nodes import is_element_set
from .render import render
from .text import TextMode, concatenate_descendant_text, extract_text


@dataclass(frozen=True)
class OutputOptions:
    """The output flags in force for one run, after CSS mode silenced its own."""

    text_mode: TextMode | None
    union: bool
    json: bool
    first: bool
    compact: bool


def present(result, options: OutputOptions) -> str:
    """Render `result` under `options`, the highest-ranked flag that applies winning."""
    if (
        options.union
        and options.text_mode is TextMode.DESCENDANT
        and is_element_set(result)
    ):
        concatenated = concatenate_descendant_text(result, options.first)
        return f"{concatenated}\n" if concatenated else ""
    extracted = extract_text(result, options.text_mode)
    if options.json and is_element_set(extracted):
        return export(extracted, options.compact, options.first)
    return render(extracted, options.first, options.compact)
