"""Laying out what one `sync` run changed, as the post-sync summary."""

from collections import Counter

from . import viewer_links
from .history import current_value
from .schema import CATEGORIES
from .sync import CHANGE_KINDS


def render(name, stamp, changes):
    """The summary text: the run's counts, then the entries behind them."""
    counts = Counter(change.kind for change in changes)
    lines = [
        f"synced vault '{name}' at {stamp}",
        "changes: " + ", ".join(f"{counts[kind]} {kind}" for kind in CHANGE_KINDS),
    ]
    for category in CATEGORIES:
        lines.extend(_section(name, category, [change for change in changes if change.category == category]))
    return "\n".join(lines)


def _section(name, category, changes):
    """One category's changed entries, grouped by change kind."""
    if not changes:
        return []

    lines = [category.capitalize()]
    for kind in CHANGE_KINDS:
        of_kind = [change for change in changes if change.kind == kind]
        if of_kind:
            lines.append(f"  {kind.capitalize()}:")
            lines.extend(_entry_line(name, category, change.entry) for change in of_kind)
    return lines


def _entry_line(name, category, entry):
    """An entry's current title and its viewer link, on one line."""
    link = viewer_links.entry_url(name, category, entry["id"])
    return f"    - {current_value(entry['title'])} {link}"
