"""Laying a :class:`~mvaultlib.vault_view.VaultView` out as the `digest` report."""

from . import viewer_links
from .digest import GROUPS, classify
from .vault_view import current_title

NO_CHANGES = "No notable changes found."

#: How a `removed` value that has gone back to false is named in a change list.
REAPPEARED = "reappeared"


def render(name, view, stamp):
    """The digest text for `view`, its trailing run-metadata line included."""
    lines = []
    for category, entries in view.categories:
        section = _section(name, category, entries, view)
        if section:
            lines.append(category.capitalize())
            lines.extend(section)

    body = lines or [NO_CHANGES]
    return "\n".join([*body, _trailing_line(name, view, stamp)])


def _section(name, category, entries, view):
    """One category's change lines, grouped by type; empty if nothing qualifies."""
    grouped = {group: [] for group in GROUPS}
    for entry in entries:
        classified = classify(entry, view)
        if classified:
            group, changed = classified
            grouped[group].append(_entry_line(name, category, entry, view, changed))

    lines = []
    for group in GROUPS:
        if grouped[group]:
            lines.append(f"  {group}:")
            lines.extend(grouped[group])
    return lines


def _entry_line(name, category, entry, view, changed):
    """An entry's title, what changed about it, and its viewer link."""
    link = viewer_links.entry_url(name, category, entry["id"])
    return f"    - {current_title(entry, view)}{_suffix(changed)} {link}"


def _suffix(changed):
    """The parenthesised change list that follows an updated entry's title."""
    if not changed:
        return ""
    names = [REAPPEARED if field == "removed" else field for field in changed]
    return f" ({', '.join(names)})"


def _trailing_line(name, view, stamp):
    """What the digest was run against, and when."""
    return f"digest of vault '{name}' (version {view.version}) generated {stamp} from {view.source}"
