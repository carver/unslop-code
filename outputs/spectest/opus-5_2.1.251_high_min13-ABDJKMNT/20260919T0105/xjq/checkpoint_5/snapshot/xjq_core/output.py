"""Picking the form the results are printed in.

The output flags do not each own a stage: `--text-all` over `--text` over
`--json` is a precedence, and a union query changes what `--text-all` means.
`OutputOptions` carries that decision once the CLI has resolved the flags, and
`format_results` follows it.
"""

from dataclasses import dataclass

from lxml import etree

from .extraction import DESCENDANT, extract_text, joined_text
from .json_export import export_json
from .rendering import render


@dataclass(frozen=True)
class OutputOptions:
    """What the output flags ask for, once their precedence is settled.

    `text_mode` is the extraction `--text`/`--text-all` want, already reduced
    to `None` where the query makes them no-ops. `json_export` is `--json`
    after the flags that outrank it have had their say. `union` records that
    the query joins several paths with `|`, which makes `--text-all`
    concatenate its matches instead of listing them.
    """

    text_mode: str = None
    json_export: bool = False
    first: bool = False
    compact: bool = False
    union: bool = False


def format_results(results, options):
    """Return the text to print for `results`, or `None` to print nothing."""
    if options.union and options.text_mode == DESCENDANT:
        return joined_text(_limited(results, options.first)) or None

    values = extract_text(results, options.text_mode)
    if options.json_export and _holds_elements(values):
        return export_json(_limited(values, options.first), compact=options.compact)
    return render(values, first=options.first, compact=options.compact)


def _limited(values, first):
    """Cut `values` down to its first entry when `--first` is active."""
    return values[:1] if first else values


def _holds_elements(values):
    """True when the results auto-format as XML nodes rather than as text."""
    return isinstance(values, list) and bool(values) and etree.iselement(values[0])
